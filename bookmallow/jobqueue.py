"""Single-worker FIFO queue driving metadata fetch, conversion and retention (spec §6.2–6.8)."""
from __future__ import annotations

import errno
import logging
import os
import queue
import shutil
import threading
from typing import Callable

from . import metadata as md
from . import names, retention
from .config import QUALITIES, Config
from .converter import Cancelled, Conversion, ConversionError, ConvertRequest
from .jobs import Job, Status, new_book_job, new_job, now_iso
from .procutil import unlink_quietly
from .state import StateStore
from .store.assemble import AssembleRequest, Assembly
from .store.models import BookPlan, SearchResult, StoreError
from .store.providers import archive, librivox
from .store.qbittorrent import QbtClient
from .store.torrent import TorrentAcquisition

log = logging.getLogger(__name__)
MB = 1024 * 1024


class DuplicateJob(Exception):
    def __init__(self, job: Job):
        super().__init__(f"job for {job.video_id} is already queued")
        self.job = job


def estimate_bytes(duration: int | None, quality: str) -> int:
    if not duration:
        return 0
    return int(duration * QUALITIES[quality]["kbps"] * 1000 / 8 * 1.1)


def default_plan_for(source: str, source_id: str, config: Config) -> BookPlan:
    if source == "librivox":
        return librivox.plan(source_id, timeout=config.store_timeout_s)
    if source == "archive":
        return archive.plan(source_id, timeout=config.store_timeout_s)
    raise StoreError("store_disabled", f"no plan provider for source {source!r}")


def estimate_book_bytes(duration: int | None, size_bytes: int | None, bitrate: str, copy_audio: bool = False) -> int:
    """Disk needed for the M4B: the sources' size when they are copied as-is, else duration × bitrate."""
    if copy_audio and size_bytes:
        return int(size_bytes * 1.05)
    kbps = int(bitrate.lower().rstrip("k") or 64)
    if duration:
        return int(duration * kbps * 1000 / 8 * 1.1)
    return int((size_bytes or 0) * 1.1)


class JobQueue:
    def __init__(self, config: Config, store: StateStore, *,
                 fetch_video: Callable[[str], md.VideoMeta] = md.fetch_video,
                 conversion_factory=Conversion,
                 disk_usage=shutil.disk_usage,
                 plan_for=default_plan_for,
                 assembly_factory=Assembly,
                 torrent_factory=TorrentAcquisition,
                 qbt_client_factory=QbtClient):
        self.config = config
        self.store = store
        self._fetch_video = fetch_video
        self._conversion_factory = conversion_factory
        self._disk_usage = disk_usage
        self._plan_for = plan_for
        self._assembly_factory = assembly_factory
        self._torrent_factory = torrent_factory
        self._qbt_client_factory = qbt_client_factory
        self.jobs: list[Job] = []
        self._results: dict[str, SearchResult] = {}
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.RLock()
        self._current: object | None = None
        self._current_id: str | None = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------------------------

    def recover(self) -> None:
        """Reload state.json, fail interrupted jobs, requeue queued ones, clean partials (spec §6.8)."""
        with self._lock:
            self.jobs = self.store.load()
            orphan_hashes: list[str] = []
            for job in self.jobs:
                if job.status in (Status.FETCHING, Status.CONVERTING):
                    job.status, job.error_code, job.error = Status.FAILED, "interrupted", "interrupted by a restart"
                    job.finished_at = now_iso()
                    if job.kind == "book" and job.torrent_hash:
                        orphan_hashes.append(job.torrent_hash)
                elif job.status is Status.QUEUED and job.kind == "book" and job.source == "prowlarr":
                    job.status, job.error_code, job.error = Status.FAILED, "interrupted", "download link lost after a restart"
                    job.finished_at = now_iso()
            for job in sorted((j for j in self.jobs if j.status is Status.QUEUED), key=lambda j: j.created_at):
                self._pending.put(job.id)
            for path in retention.remove_partials(self.config.data_dir):
                log.info("removed partial file %s", path.name)
            shutil.rmtree(self.config.work_dir, ignore_errors=True)
            for path in retention.prune(self.config.data_dir, self.config.max_files):
                log.info("retention: deleted %s", path.name)
            self._save()
        for torrent_hash in orphan_hashes:
            self._cleanup_orphan(torrent_hash)

    def _cleanup_orphan(self, torrent_hash: str) -> None:
        if not self.config.torrent_enabled:
            return
        try:
            client = self._qbt_client_factory(self.config.qbt_url, self.config.qbt_user, self.config.qbt_password,
                                              timeout=self.config.store_timeout_s)
            client.login()
            client.delete(torrent_hash, delete_files=True)
            log.info("removed orphan torrent %s after restart", torrent_hash)
        except Exception as exc:  # noqa: BLE001 - best effort at startup
            log.warning("could not remove orphan torrent %s: %s", torrent_hash, exc)

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

    def submit_book(self, result: SearchResult, quality: str | None = None) -> Job:
        quality = quality or self.config.default_quality
        with self._lock:
            for existing in self.jobs:
                if existing.video_id == result.key and existing.is_active:
                    raise DuplicateJob(existing)
            job = new_book_job(result.source, result.source_id, result.title, result.author, result.language,
                               result.duration, result.cover, quality)
            self._results[job.id] = result
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
            self._results.pop(job_id, None)
            self._save()
            conv = self._current if self._current_id == job_id else None
        if conv is not None:
            conv.cancel()
        return True

    def remove(self, job_id: str) -> bool:
        """Forget a finished job (failed, cancelled or done). Active jobs must be cancelled first."""
        with self._lock:
            job = self.get(job_id)
            if job is None or job.is_active:
                return False
            self.jobs = [j for j in self.jobs if j.id != job_id]
            self._results.pop(job_id, None)
            self._save()
            return True

    def clear_history(self) -> int:
        """Forget every finished job except the done ones whose file is still in the library."""
        with self._lock:
            present = {p.name for p in retention.list_audio(self.config.data_dir)}
            keep = [j for j in self.jobs if j.is_active or (j.status is Status.DONE and j.filename in present)]
            removed = len(self.jobs) - len(keep)
            if removed:
                for j in self.jobs:
                    if j not in keep:
                        self._results.pop(j.id, None)
                self.jobs = keep
                self._save()
            return removed

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
            self._results.pop(job_id, None)
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
        if job.kind == "book":
            self._process_book(job)
            return
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
            self._fail(job, exc.code, exc.detail, tail=exc.tail)
            return
        finally:
            with self._lock:
                self._current, self._current_id = None, None

        with self._lock:
            if job.status is Status.CANCELLED:
                out_path.unlink(missing_ok=True)
                self._save()
                return
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

    def _process_book(self, job: Job) -> None:
        with self._lock:
            job.status, job.started_at = Status.FETCHING, now_iso()
            self._save()
        result = self._results.pop(job.id, None)
        acq = None
        try:
            if job.source == "prowlarr":
                if result is None or not result.download:
                    raise StoreError("interrupted", "download link lost after a restart")
                if not self.config.torrent_enabled:
                    raise StoreError("store_disabled", "torrent support is not configured")
                client = self._qbt_client_factory(self.config.qbt_url, self.config.qbt_user, self.config.qbt_password,
                                                  timeout=self.config.store_timeout_s)
                acq = self._torrent_factory(client, result, self.config, job.id, on_progress=lambda p: self._progress(job, p))
                with self._lock:
                    if job.status is Status.CANCELLED:
                        return
                    self._current, self._current_id = acq, job.id
                torrent_hash = acq.start()
                with self._lock:
                    job.torrent_hash = torrent_hash
                    self._save()
                plan = acq.plan(acq.wait())
                copy_audio, single_file, base, scale = acq.copy_audio, acq.single_file, 50.0, 0.5
            else:
                plan = self._plan_for(job.source, job.source_id, self.config)
                copy_audio, single_file, base, scale = False, None, 0.0, 1.0

            with self._lock:
                if job.status is Status.CANCELLED:
                    return
                job.title = plan.title or job.title
                job.author = plan.author or job.author
                job.language = plan.language or job.language
                job.duration = plan.duration or job.duration
                job.cover = job.cover or plan.cover
                job.thumbnail = job.cover
                reason = self._guard_book(job, result, copy_audio=copy_audio or single_file is not None)
            if reason is not None:
                raise StoreError(*reason)

            out_path = self._book_target_path(job)
            if single_file is not None:
                self._copy_single(job, single_file, out_path)
            else:
                req = AssembleRequest(tracks=plan.tracks, out_path=out_path, work_dir=self.config.work_dir / job.id,
                                      title=job.title or "Audiobook", author=job.author, language=job.language,
                                      duration=job.duration, cover=None if job.source == "prowlarr" else plan.cover,
                                      bitrate=self.config.book_bitrate, copy_audio=copy_audio,
                                      source_url=result.url if result else None)
                asm = self._assembly_factory(req, on_progress=lambda p: self._progress(job, base + p * scale))
                with self._lock:
                    if job.status is Status.CANCELLED:
                        return
                    self._current, self._current_id = asm, job.id
                    job.status = Status.CONVERTING
                    self._save()
                asm.run()

            with self._lock:
                if job.status is Status.CANCELLED:
                    out_path.unlink(missing_ok=True)
                    self._save()
                    return
                job.filename = out_path.name
                job.size_bytes = out_path.stat().st_size if out_path.exists() else None
                job.progress = 100.0
                self._finish(job, Status.DONE)
                deleted = retention.prune(self.config.data_dir, self.config.max_files)
            for path in deleted:
                log.info("retention: deleted %s", path.name)
        except Cancelled:
            self._finish(job, Status.CANCELLED)
        except (StoreError, ConversionError) as exc:
            self._fail(job, exc.code, exc.detail, tail=getattr(exc, "tail", ""))
        finally:
            with self._lock:
                self._current, self._current_id = None, None
            if acq is not None:
                acq.cleanup()

    def _guard_book(self, job: Job, result: SearchResult | None, copy_audio: bool = False) -> tuple[str, str] | None:
        hours = self.config.max_duration_hours
        if hours > 0 and job.duration and job.duration > hours * 3600:
            return "too_long", f"longer than {hours:g} h"
        need = estimate_book_bytes(job.duration, result.size_bytes if result else None, self.config.book_bitrate,
                                   copy_audio=copy_audio)
        free = self._disk_usage(str(self.config.data_dir)).free
        if free - need < self.config.min_free_mb * MB:
            return "no_space", f"about {need // MB} MB needed, {free // MB} MB free"
        return None

    def _book_target_path(self, job: Job):
        tag = names.safe_tag(job.author, job.source_id or "book")
        existing = {p.name for p in self.config.data_dir.iterdir()}
        return self.config.data_dir / names.unique_name(names.safe_filename(job.title, tag, ext=".m4b"), existing)

    def _copy_single(self, job: Job, src, out_path) -> None:
        """A torrent that already is one M4B: copy it as-is, no re-encoding."""
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            job.status = Status.CONVERTING
            self._save()
        part = retention.part_path(out_path)
        try:
            shutil.copyfile(src, part)
            os.replace(part, out_path)
        except OSError as exc:
            unlink_quietly(part)
            code = "no_space" if exc.errno == errno.ENOSPC else "internal"
            raise StoreError(code, f"could not copy the M4B: {exc.strerror or exc.__class__.__name__}") from exc

    def _progress(self, job: Job, percent: float) -> None:
        with self._lock:
            if job.status is Status.CONVERTING or (job.kind == "book" and job.status is Status.FETCHING):
                job.progress = round(percent, 1)

    def _fail(self, job: Job, code: str, detail: str, tail: str = "") -> None:
        log.warning("job %s failed [%s]: %s", job.id, code, detail)
        if tail:
            log.warning("job %s ffmpeg/yt-dlp stderr tail:\n%s", job.id, tail)
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
