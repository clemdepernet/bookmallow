"""Single-worker FIFO queue driving metadata fetch, conversion and retention (spec §6.2–6.8)."""
from __future__ import annotations

import logging
import queue
import shutil
import threading
from typing import Callable

from . import metadata as md
from . import names, retention
from .config import QUALITIES, Config
from .converter import Cancelled, Conversion, ConversionError, ConvertRequest
from .jobs import Job, Status, new_job, now_iso
from .state import StateStore

log = logging.getLogger(__name__)
MB = 1024 * 1024


class DuplicateJob(Exception):
    def __init__(self, job: Job):
        super().__init__(f"video {job.video_id} is already queued")
        self.job = job


def estimate_bytes(duration: int | None, quality: str) -> int:
    if not duration:
        return 0
    return int(duration * QUALITIES[quality]["kbps"] * 1000 / 8 * 1.1)


class JobQueue:
    def __init__(self, config: Config, store: StateStore, *,
                 fetch_video: Callable[[str], md.VideoMeta] = md.fetch_video,
                 conversion_factory=Conversion,
                 disk_usage=shutil.disk_usage):
        self.config = config
        self.store = store
        self._fetch_video = fetch_video
        self._conversion_factory = conversion_factory
        self._disk_usage = disk_usage
        self.jobs: list[Job] = []
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.RLock()
        self._current: Conversion | None = None
        self._current_id: str | None = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------------------------

    def recover(self) -> None:
        """Reload state.json, fail interrupted jobs, requeue queued ones, clean partials (spec §6.8)."""
        with self._lock:
            self.jobs = self.store.load()
            for job in self.jobs:
                if job.status in (Status.FETCHING, Status.CONVERTING):
                    job.status = Status.FAILED
                    job.error_code = "interrupted"
                    job.error = "interrupted by a restart"
                    job.finished_at = now_iso()
            for job in sorted((j for j in self.jobs if j.status is Status.QUEUED), key=lambda j: j.created_at):
                self._pending.put(job.id)
            for path in retention.remove_partials(self.config.data_dir):
                log.info("removed partial file %s", path.name)
            for path in retention.prune(self.config.data_dir, self.config.max_files):
                log.info("retention: deleted %s", path.name)
            self._save()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._work, name="bookmallow-worker", daemon=True)
        self._thread.start()

    # ---- public API ------------------------------------------------------------------------

    def submit(self, url: str, video_id: str, quality: str) -> Job:
        with self._lock:
            for existing in self.jobs:
                if existing.video_id == video_id and existing.is_active:
                    raise DuplicateJob(existing)
            job = new_job(url, video_id, quality)
            self.jobs.append(job)
            self._pending.put(job.id)
            self._save()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None or not job.is_active:
                return False
            job.status = Status.CANCELLED
            job.finished_at = now_iso()
            self._save()
            conv = self._current if self._current_id == job_id else None
        if conv is not None:
            conv.cancel()
        return True

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self.jobs]

    # ---- worker ----------------------------------------------------------------------------

    def process_next(self, block: bool = True, timeout: float | None = None) -> bool:
        """Take one queued job and run it to completion. Returns False if nothing was pending."""
        try:
            job_id = self._pending.get(block=block, timeout=timeout)
        except queue.Empty:
            return False
        job = self.get(job_id)
        if job is None or job.status is not Status.QUEUED:
            return True
        try:
            self._process(job)
        except Exception:  # noqa: BLE001 - the worker must survive anything
            log.exception("job %s crashed", job.id)
            self._fail(job, "internal", "unexpected error, see server logs")
        return True

    def _work(self) -> None:
        while True:
            try:
                self.process_next()
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")

    def _process(self, job: Job) -> None:
        with self._lock:
            job.status = Status.FETCHING
            job.started_at = now_iso()
            self._save()
        try:
            meta = self._fetch_video(job.url)
        except md.MetadataError as exc:
            self._fail(job, exc.code, exc.detail)
            return
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            job.title, job.duration = meta.title, meta.duration
            job.thumbnail, job.channel = meta.thumbnail, meta.channel
            reason = self._guard(job)
        if reason is not None:
            self._fail(job, *reason)
            return

        out_path = self._target_path(job)
        req = ConvertRequest(url=job.url, quality=job.quality, out_path=out_path, duration=job.duration,
                             title=job.title, channel=job.channel, chapters=meta.chapters)
        conv = self._conversion_factory(req, on_progress=lambda p: self._progress(job, p))
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            self._current, self._current_id = conv, job.id
            job.status = Status.CONVERTING
            self._save()
        try:
            conv.run()
        except Cancelled:
            self._finish(job, Status.CANCELLED)
            return
        except ConversionError as exc:
            self._fail(job, exc.code, exc.detail)
            return
        finally:
            with self._lock:
                self._current, self._current_id = None, None

        with self._lock:
            job.filename = out_path.name
            job.size_bytes = out_path.stat().st_size if out_path.exists() else None
            job.progress = 100.0
            self._finish(job, Status.DONE)
            deleted = retention.prune(self.config.data_dir, self.config.max_files)
        for path in deleted:
            log.info("retention: deleted %s", path.name)

    def _guard(self, job: Job) -> tuple[str, str] | None:
        hours = self.config.max_duration_hours
        if hours > 0 and job.duration and job.duration > hours * 3600:
            return "too_long", f"longer than {hours:g} h"
        need = estimate_bytes(job.duration, job.quality)
        free = self._disk_usage(str(self.config.data_dir)).free
        if free - need < self.config.min_free_mb * MB:
            return "no_space", f"about {need // MB} MB needed, {free // MB} MB free"
        return None

    def _target_path(self, job: Job):
        existing = {p.name for p in self.config.data_dir.iterdir()}
        return self.config.data_dir / names.unique_name(names.safe_filename(job.title, job.video_id), existing)

    def _progress(self, job: Job, percent: float) -> None:
        with self._lock:
            if job.status is Status.CONVERTING:
                job.progress = round(percent, 1)

    def _fail(self, job: Job, code: str, detail: str) -> None:
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            job.error_code, job.error = code, detail
            self._finish(job, Status.FAILED)

    def _finish(self, job: Job, status: Status) -> None:
        with self._lock:
            job.status = status
            job.finished_at = now_iso()
            self._save()

    def _save(self) -> None:
        with self._lock:
            self.jobs = self.store.save(self.jobs)
