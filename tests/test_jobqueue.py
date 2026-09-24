from __future__ import annotations

import shutil
from collections import namedtuple
from dataclasses import replace
from pathlib import Path

import pytest

from bookmallow import jobqueue as jq
from bookmallow.converter import Cancelled, ConversionError
from bookmallow.jobs import Status, new_job
from bookmallow.metadata import MetadataError, VideoMeta
from bookmallow.state import StateStore
from bookmallow.store.models import BookPlan, SearchResult, StoreError, Track
from bookmallow.store.qbittorrent import TorrentInfo

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


LIBRI = SearchResult("librivox", "904", "Boule de suif", author="Guy de Maupassant", language="fr", duration=1000,
                     cover="https://c/x.jpg", url="https://librivox.org/x")
TORR = SearchResult("prowlarr", "abc", "Dune", author="Idx", language="en", size_bytes=5000, download="magnet:?xt=1", url="https://idx/t")
PLAN = BookPlan("Boule de suif", "Guy de Maupassant", "fr", 1000, "https://c/x.jpg", [Track("https://a/1.mp3", 500.0, "Un"), Track("https://a/2.mp3", 500.0, "Deux")])


class FakeAssembly:
    instances: list["FakeAssembly"] = []
    behaviour = "ok"

    def __init__(self, req, on_progress=None):
        self.req, self.on_progress, self.cancelled = req, on_progress or (lambda p: None), False
        FakeAssembly.instances.append(self)

    def run(self):
        self.on_progress(50.0)
        if FakeAssembly.behaviour == "fail":
            raise ConversionError("ffmpeg", "boom", tail="l1\nl2")
        if self.cancelled:
            raise Cancelled()
        self.req.out_path.write_bytes(b"m4b" * 100)

    def cancel(self):
        self.cancelled = True


class FakeTorrent:
    instances: list["FakeTorrent"] = []
    behaviour = "ok"  # ok | single | stall | cancel_in_wait
    single_path: Path | None = None

    def __init__(self, client, result, config, job_id, on_progress=None, **kw):
        self.client, self.result, self.config, self.job_id = client, result, config, job_id
        self.on_progress = on_progress or (lambda p: None)
        self.hash, self.cleaned, self.cancelled = None, False, False
        self.copy_audio, self.single_file = True, None
        FakeTorrent.instances.append(self)

    def start(self):
        self.hash = "h1"
        return "h1"

    def wait(self):
        self.on_progress(25.0)
        if FakeTorrent.behaviour == "stall":
            from bookmallow.store.qbittorrent import QbtError
            raise QbtError("torrent_stalled", "no data")
        if FakeTorrent.behaviour == "cancel_in_wait" or self.cancelled:
            raise Cancelled()
        return TorrentInfo("h1", "Dune", 1.0, "uploading", "/downloads/bookmallow/Dune", 5000, 5000)

    def plan(self, info):
        if FakeTorrent.behaviour == "single":
            self.single_file = FakeTorrent.single_path
        return BookPlan("Dune", "Idx", "en", 3600, None, [Track("/incoming/bookmallow/Dune/01.m4a", 3600.0, "01")])

    def cleanup(self):
        self.cleaned = True

    def cancel(self):
        self.cancelled = True


class FakeQbt:
    created: list["FakeQbt"] = []

    def __init__(self, url, user, password, timeout=20.0):
        self.url, self.deleted, self.logged = url, [], False
        FakeQbt.created.append(self)

    def login(self):
        self.logged = True

    def delete(self, h, delete_files=True):
        self.deleted.append((h, delete_files))


@pytest.fixture
def bq(config):
    """A queue with book fakes; torrent configured."""
    FakeAssembly.instances, FakeTorrent.instances, FakeQbt.created = [], [], []
    FakeAssembly.behaviour, FakeTorrent.behaviour = "ok", "ok"
    cfg = replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    queue = jq.JobQueue(cfg, StateStore(cfg.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11), plan_for=lambda s, sid, c: PLAN,
                        assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    return queue


def test_estimate_book_bytes():
    assert jq.estimate_book_bytes(3600, None, "64k") == int(3600 * 64 * 1000 / 8 * 1.1)
    assert jq.estimate_book_bytes(None, 5000, "64k") == 5500
    assert jq.estimate_book_bytes(None, None, "64k") == 0


def test_submit_book_dedupes_on_key(bq):
    job = bq.submit_book(LIBRI)
    assert job.kind == "book" and job.video_id == "librivox:904" and job.quality == "64"
    with pytest.raises(jq.DuplicateJob):
        bq.submit_book(LIBRI)


def test_cancelled_queued_book_does_not_leak_result(bq):
    job = bq.submit_book(LIBRI)
    assert job.id in bq._results
    assert bq.cancel(job.id) is True
    assert job.id not in bq._results
    assert bq.process_next(block=False) is True  # popped and skipped
    assert job.id not in bq._results and FakeAssembly.instances == []


def test_free_book_flow(bq):
    job = bq.submit_book(LIBRI)
    assert bq.process_next(block=False)
    job = bq.get(job.id)
    assert job.status is Status.DONE and job.filename == "Boule de suif [Guy de Maupassant].m4b" and job.progress == 100.0
    assert (bq.config.data_dir / job.filename).exists() and job.size_bytes == 300
    req = FakeAssembly.instances[0].req
    assert req.work_dir == bq.config.work_dir / job.id and req.cover == "https://c/x.jpg" and req.bitrate == "64k"
    assert req.copy_audio is False and req.source_url == "https://librivox.org/x" and len(req.tracks) == 2
    assert FakeTorrent.instances == []


def test_free_book_plan_error(bq):
    bq._plan_for = lambda s, sid, c: (_ for _ in ()).throw(StoreError("not_found", "gone"))
    job = bq.submit_book(LIBRI)
    bq.process_next(block=False)
    assert bq.get(job.id).status is Status.FAILED and bq.get(job.id).error_code == "not_found"


def test_torrent_book_flow_scales_progress_and_cleans_up(bq):
    seen = []
    job = bq.submit_book(TORR)
    orig = bq._progress
    bq._progress = lambda j, p: (seen.append(p), orig(j, p))
    bq.process_next(block=False)
    job = bq.get(job.id)
    assert job.status is Status.DONE and job.torrent_hash == "h1" and job.filename == "Dune [Idx].m4b"
    assert seen == [25.0, 75.0]  # wait → 25 ; assembly 50 → 50 + 50/2
    acq = FakeTorrent.instances[0]
    assert acq.cleaned is True and FakeQbt.created[0].url == "http://q"
    req = FakeAssembly.instances[0].req
    assert req.copy_audio is True and req.cover is None and req.tracks[0].location.startswith("/incoming")


def test_torrent_single_m4b_is_copied_not_assembled(bq, tmp_path):
    src = tmp_path / "src.m4b"
    src.write_bytes(b"ready")
    FakeTorrent.behaviour, FakeTorrent.single_path = "single", src
    job = bq.submit_book(TORR)
    bq.process_next(block=False)
    job = bq.get(job.id)
    assert job.status is Status.DONE and (bq.config.data_dir / job.filename).read_bytes() == b"ready"
    assert FakeAssembly.instances == [] and FakeTorrent.instances[0].cleaned


def test_torrent_stall_fails_and_cleans(bq):
    FakeTorrent.behaviour = "stall"
    job = bq.submit_book(TORR)
    bq.process_next(block=False)
    assert bq.get(job.id).error_code == "torrent_stalled" and FakeTorrent.instances[0].cleaned


def test_torrent_disabled_fails_cleanly(config):
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11), plan_for=lambda s, sid, c: PLAN,
                        assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    job = queue.submit_book(TORR)
    queue.process_next(block=False)
    assert queue.get(job.id).error_code == "store_disabled"


def test_cancel_during_torrent_wait(bq):
    job = bq.submit_book(TORR)

    class CancellingTorrent(FakeTorrent):
        def wait(self):
            bq.cancel(job.id)
            return super().wait()

    bq._torrent_factory = CancellingTorrent
    bq.process_next(block=False)
    assert bq.get(job.id).status is Status.CANCELLED and FakeTorrent.instances[0].cancelled and FakeTorrent.instances[0].cleaned
    assert not list(bq.config.data_dir.glob("*.m4b"))


def test_book_disk_guard_uses_size(config):
    cfg = replace(config, min_free_mb=1, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    queue = jq.JobQueue(cfg, StateStore(cfg.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**9, 0, 1_500_000), plan_for=lambda s, sid, c: BookPlan("T", None, None, None, None, [Track("u")]),
                        assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    big = replace(TORR, size_bytes=900_000)  # 990 000 needed, leaves 510 000 < 1 MB
    job = queue.submit_book(big)
    queue.process_next(block=False)
    assert queue.get(job.id).error_code == "no_space" and FakeTorrent.instances[-1].cleaned


def test_recover_cleans_orphan_torrent_and_queued_prowlarr(config):
    cfg = replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    store = StateStore(cfg.state_path)
    from bookmallow.jobs import new_book_job
    converting = new_book_job("prowlarr", "abc", "Dune", "Idx", "en", None, None, "64")
    converting.status, converting.torrent_hash = Status.CONVERTING, "h1"
    queued_t = new_book_job("prowlarr", "def", "Other", None, None, None, None, "64")
    queued_l = new_book_job("librivox", "1", "Libre", None, "fr", 10, None, "64")
    store.save([converting, queued_t, queued_l])
    (cfg.work_dir / "old").mkdir(parents=True)
    FakeQbt.created = []
    queue = jq.JobQueue(cfg, store, fetch_video=meta_for, conversion_factory=FakeConversion, disk_usage=lambda p: Usage(1, 0, 10**11),
                        plan_for=lambda s, sid, c: PLAN, assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    assert queue.get(converting.id).status is Status.FAILED and FakeQbt.created[0].deleted == [("h1", True)]
    assert queue.get(queued_t.id).status is Status.FAILED and queue.get(queued_t.id).error_code == "interrupted"
    assert queue.get(queued_l.id).status is Status.QUEUED and not cfg.work_dir.exists()
    queue.process_next(block=False)
    assert queue.get(queued_l.id).status is Status.DONE


def test_youtube_flow_unchanged_with_book_fakes(bq):
    job = bq.submit(URL, "aaaaaaaaaaa", "64")
    bq.process_next(block=False)
    assert bq.get(job.id).status is Status.DONE and bq.get(job.id).kind == "youtube"
