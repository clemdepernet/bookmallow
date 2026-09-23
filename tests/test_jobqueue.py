from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from bookmallow import jobqueue as jq
from bookmallow.converter import Cancelled, ConversionError
from bookmallow.jobs import Status, new_job
from bookmallow.metadata import MetadataError, VideoMeta
from bookmallow.state import StateStore

Usage = namedtuple("Usage", "total used free")
URL = "https://www.youtube.com/watch?v=aaaaaaaaaaa"


def meta_for(url):
    vid = url[-11:]
    return VideoMeta(video_id=vid, title=f"Titre {vid}", duration=3600, thumbnail="https://i/x.jpg", channel="Chaîne", chapters=[])


class FakeConversion:
    instances: list["FakeConversion"] = []
    behaviour = "ok"  # "ok" | "fail" | "cancel"

    def __init__(self, req, on_progress=None):
        self.req = req
        self.on_progress = on_progress or (lambda p: None)
        self.cancelled = False
        FakeConversion.instances.append(self)

    def run(self):
        self.on_progress(42.0)
        if FakeConversion.behaviour == "fail":
            raise ConversionError("ffmpeg", "boom")
        if FakeConversion.behaviour == "cancel" or self.cancelled:
            raise Cancelled()
        self.req.out_path.write_bytes(b"x" * 1000)

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def q(config):
    FakeConversion.instances = []
    FakeConversion.behaviour = "ok"
    store = StateStore(config.state_path)
    queue = jq.JobQueue(config, store, fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    return queue


def test_estimate_bytes():
    assert jq.estimate_bytes(None, "64") == 0
    assert jq.estimate_bytes(3600, "64") == int(3600 * 64 * 1000 / 8 * 1.1)
    assert jq.estimate_bytes(3600, "192") == 3 * jq.estimate_bytes(3600, "64")


def test_submit_then_process_produces_file(q, config):
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    assert job.status is Status.QUEUED
    assert q.process_next(block=False) is True
    job = q.get(job.id)
    assert job.status is Status.DONE
    assert job.title == "Titre aaaaaaaaaaa" and job.duration == 3600 and job.channel == "Chaîne"
    assert job.filename == "Titre aaaaaaaaaaa [aaaaaaaaaaa].mp3"
    assert (config.data_dir / job.filename).stat().st_size == 1000
    assert job.size_bytes == 1000 and job.progress == 100.0
    assert job.started_at and job.finished_at
    assert q.process_next(block=False) is False
    assert FakeConversion.instances[0].req.quality == "64"
    assert StateStore(config.state_path).load()[0].status is Status.DONE


def test_duplicate_active_video_is_refused(q):
    first = q.submit(URL, "aaaaaaaaaaa", "64")
    with pytest.raises(jq.DuplicateJob) as exc:
        q.submit(URL, "aaaaaaaaaaa", "128")
    assert exc.value.job.id == first.id
    q.process_next(block=False)
    q.submit(URL, "aaaaaaaaaaa", "128")  # allowed again once finished


def test_fifo_order(q):
    ids = [q.submit(URL[:-11] + f"{c * 11}", c * 11, "64").id for c in "abc"]
    for expected in ids:
        q.process_next(block=False)
        done = [j for j in q.jobs if j.status is Status.DONE]
        assert done[-1].id == expected


def test_metadata_error_fails_job(q):
    q._fetch_video = lambda url: (_ for _ in ()).throw(MetadataError("private", "Private video"))
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.process_next(block=False)
    job = q.get(job.id)
    assert job.status is Status.FAILED and job.error_code == "private" and job.error == "Private video"


def test_conversion_error_fails_job(q):
    FakeConversion.behaviour = "fail"
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.process_next(block=False)
    assert q.get(job.id).status is Status.FAILED
    assert q.get(job.id).error_code == "ffmpeg"


def test_conversion_error_tail_is_logged_server_side(q, caplog):
    """finding #2: a multi-line stderr tail must not end up in job.error, but must reach the logs."""
    class TailFailingConversion(FakeConversion):
        def run(self):
            raise ConversionError("ffmpeg", "line 5", tail="line 1\nline 2\nline 3\nline 4\nline 5")

    q._conversion_factory = TailFailingConversion
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    with caplog.at_level("WARNING"):
        q.process_next(block=False)
    job = q.get(job.id)
    assert job.status is Status.FAILED
    assert job.error == "line 5" and "\n" not in job.error
    assert any("failed [ffmpeg]" in r.message for r in caplog.records)
    assert any("line 1\nline 2\nline 3\nline 4\nline 5" in r.message for r in caplog.records)


def test_disk_guard(config):
    FakeConversion.instances = []
    config = config.__class__(**{**config.__dict__, "min_free_mb": 100})
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**9, 0, 120 * jq.MB))
    queue.recover()
    job = queue.submit(URL, "aaaaaaaaaaa", "64")  # needs ~31 MB, leaves 89 MB < 100 MB
    queue.process_next(block=False)
    assert queue.get(job.id).status is Status.FAILED
    assert queue.get(job.id).error_code == "no_space"
    assert FakeConversion.instances == []


def test_duration_guard(config):
    config = config.__class__(**{**config.__dict__, "max_duration_hours": 0.5})
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    job = queue.submit(URL, "aaaaaaaaaaa", "64")
    queue.process_next(block=False)
    assert queue.get(job.id).error_code == "too_long"


def test_no_duration_limit_by_default(q):
    q._fetch_video = lambda url: VideoMeta("aaaaaaaaaaa", "Long", 17 * 3600, None, None, [])
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.process_next(block=False)
    assert q.get(job.id).status is Status.DONE


def test_cancel_queued_job(q):
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    assert q.cancel(job.id) is True
    assert q.get(job.id).status is Status.CANCELLED
    assert q.process_next(block=False) is True  # popped and skipped
    assert FakeConversion.instances == []
    assert q.cancel(job.id) is False
    assert q.cancel("nope") is False


def test_cancel_during_conversion(q):
    job = q.submit(URL, "aaaaaaaaaaa", "64")

    def fetch(url):
        # cancel while the worker is between fetching and converting
        q.cancel(job.id)
        return meta_for(url)

    q._fetch_video = fetch
    q.process_next(block=False)
    assert q.get(job.id).status is Status.CANCELLED
    assert FakeConversion.instances == []


def test_cancel_while_converting_calls_conversion_cancel(q):
    import threading
    started, release = threading.Event(), threading.Event()

    class BlockingConversion(FakeConversion):
        def run(self):
            started.set()
            release.wait(timeout=5)
            if self.cancelled:
                raise Cancelled()
            self.req.out_path.write_bytes(b"x")

    q._conversion_factory = BlockingConversion
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    worker = threading.Thread(target=q.process_next, kwargs={"block": False}, daemon=True)
    worker.start()
    assert started.wait(timeout=5)
    assert q.cancel(job.id) is True
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert q.get(job.id).status is Status.CANCELLED
    assert BlockingConversion.instances[-1].cancelled is True
    assert not list(q.config.data_dir.glob("*.mp3"))


def test_cancel_landing_after_successful_run_still_wins(q):
    """cancel() in the window between conv.run() returning and the success block must not be overwritten by DONE."""
    import threading

    class RacingConversion(FakeConversion):
        def run(self):
            self.req.out_path.write_bytes(b"x" * 10)
            # simulate the race: cancel arrives right as run() returns, before the success block runs
            q.cancel(self.job_id)

    job = q.submit(URL, "aaaaaaaaaaa", "64")
    RacingConversion.job_id = job.id
    q._conversion_factory = RacingConversion
    q.process_next(block=False)
    assert q.get(job.id).status is Status.CANCELLED
    assert not list(q.config.data_dir.glob("*.mp3"))


def test_retention_runs_after_each_job(config):
    config = config.__class__(**{**config.__dict__, "max_files": 2})
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    import os, time
    for i, c in enumerate("abc"):
        queue.submit(URL[:-11] + c * 11, c * 11, "64")
        queue.process_next(block=False)
        path = config.data_dir / f"Titre {c * 11} [{c * 11}].mp3"
        if path.exists():
            t = 1_700_000_000 + i  # in the past, increasing: a < b < c
            os.utime(path, (t, t))
    names = sorted(p.name for p in config.data_dir.glob("*.mp3"))
    assert names == ["Titre bbbbbbbbbbb [bbbbbbbbbbb].mp3", "Titre ccccccccccc [ccccccccccc].mp3"]


def test_recover_marks_interrupted_requeues_and_cleans(config):
    store = StateStore(config.state_path)
    converting = new_job(URL, "aaaaaaaaaaa", "64"); converting.status = Status.CONVERTING
    queued_late = new_job(URL[:-11] + "b" * 11, "b" * 11, "64"); queued_late.created_at = "2026-02-01T00:00:00+00:00"
    queued_early = new_job(URL[:-11] + "c" * 11, "c" * 11, "64"); queued_early.created_at = "2026-01-01T00:00:00+00:00"
    store.save([converting, queued_late, queued_early])
    (config.data_dir / "wip.part.mp3").write_bytes(b"x")
    queue = jq.JobQueue(config, store, fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    assert queue.get(converting.id).status is Status.FAILED
    assert queue.get(converting.id).error_code == "interrupted"
    assert not (config.data_dir / "wip.part.mp3").exists()
    queue.process_next(block=False)
    assert queue.get(queued_early.id).status is Status.DONE
    assert queue.get(queued_late.id).status is Status.QUEUED


def test_snapshot_is_plain_dicts(q):
    q.submit(URL, "aaaaaaaaaaa", "64")
    snap = q.snapshot()
    assert isinstance(snap, list) and snap[0]["status"] == "queued"


def test_start_runs_worker_thread(q, config):
    import time
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.start()
    deadline = time.monotonic() + 3
    while q.get(job.id).status is not Status.DONE and time.monotonic() < deadline:
        time.sleep(0.02)
    assert q.get(job.id).status is Status.DONE
