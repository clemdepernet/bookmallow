from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bookmallow.converter import Cancelled
from bookmallow.store import torrent as tq
from bookmallow.store.models import SearchResult, StoreError
from bookmallow.store.qbittorrent import QbtError, TorrentInfo


def info(progress, state="downloading", downloaded=None, path="/downloads/bookmallow/Book"):
    return TorrentInfo("h1", "Book", progress, state, path, 1000, downloaded if downloaded is not None else int(progress * 1000))


class FakeClient:
    def __init__(self, infos, find_after=1):
        self.infos, self.find_after, self.calls, self.deleted = list(infos), find_after, [], []

    def login(self):
        self.calls.append("login")

    def ensure_category(self, name):
        self.calls.append(f"cat:{name}")

    def add(self, download, category, tags):
        self.calls.append(("add", download, category, tuple(tags)))

    def find_by_tag(self, tag):
        self.find_after -= 1
        return None if self.find_after >= 0 else info(0.0)

    def info(self, h):
        return self.infos.pop(0) if self.infos else None

    def delete(self, h, delete_files=True):
        self.deleted.append((h, delete_files))


RESULT = SearchResult("prowlarr", "abc", "Book Title", author="Idx", download="magnet:?xt=urn:btih:1", size_bytes=1000)


@pytest.fixture
def tconfig(config):
    return replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q", qbt_category="bookmallow",
                   qbt_path_map="/downloads:/incoming", torrent_stall_hours=1.0)


def make(client, tconfig, **kw):
    clock = kw.pop("clock", None) or Clock()
    return tq.TorrentAcquisition(client, RESULT, tconfig, "job1", kw.pop("on_progress", None), sleep=clock.sleep,
                                 clock=clock.now, prober=kw.pop("prober", lambda p: (10.0, "aac")), poll_interval=5.0, **kw), clock


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_natural_key_and_list_audio_files(tmp_path):
    assert sorted(["Ch 10.mp3", "Ch 2.mp3", "Ch 1.mp3"], key=tq.natural_key) == ["Ch 1.mp3", "Ch 2.mp3", "Ch 10.mp3"]
    (tmp_path / "disc2").mkdir()
    for name in ("disc2/03.mp3", "disc2/01.mp3", "02.mp3", "cover.jpg", "notes.txt", "10.M4A"):
        (tmp_path / name).write_bytes(b"x")
    assert [str(p.relative_to(tmp_path)) for p in tq.list_audio_files(tmp_path)] == ["02.mp3", "10.M4A", "disc2/01.mp3", "disc2/03.mp3"]
    single = tmp_path / "one.m4b"
    single.write_bytes(b"x")
    assert tq.list_audio_files(single) == [single] and tq.list_audio_files(tmp_path / "cover.jpg") == []


def test_map_path():
    assert tq.map_path("/downloads/bookmallow/Book", ("/downloads", "/incoming")) == Path("/incoming/bookmallow/Book")
    assert tq.map_path("/downloads", ("/downloads", "/incoming")) == Path("/incoming")
    assert tq.map_path("/elsewhere/x", ("/downloads", "/incoming")) is None
    assert tq.map_path("/downloadsX/y", ("/downloads", "/incoming")) is None


def test_ffprobe_parses_json_and_handles_failure(tmp_path):
    class Proc:
        returncode = 0
        stdout = '{"streams":[{"codec_name":"mp3"}],"format":{"duration":"12.5"}}'

    assert tq.ffprobe(tmp_path / "a.mp3", run=lambda *a, **k: Proc()) == (12.5, "mp3")

    class Bad:
        returncode = 1
        stdout = ""

    assert tq.ffprobe(tmp_path / "a.mp3", run=lambda *a, **k: Bad()) == (None, None)

    def boom(*a, **k):
        raise FileNotFoundError("ffprobe")

    assert tq.ffprobe(tmp_path / "a.mp3", run=boom) == (None, None)


def test_start_adds_and_finds_hash(tconfig):
    client = FakeClient([], find_after=2)
    acq, clock = make(client, tconfig)
    assert acq.start() == "h1" and acq.hash == "h1"
    assert client.calls[:2] == ["login", "cat:bookmallow"]
    assert client.calls[2] == ("add", "magnet:?xt=urn:btih:1", "bookmallow", ("bookmallow", "job-job1"))


def test_start_times_out_when_torrent_never_appears(tconfig):
    acq, clock = make(FakeClient([], find_after=10**6), tconfig, add_timeout=3.0)
    with pytest.raises(QbtError) as exc:
        acq.start()
    assert exc.value.code == "torrent_add"


def test_wait_reports_progress_then_finishes(tconfig):
    seen = []
    client = FakeClient([info(0.2), info(0.6), info(1.0, "uploading")])
    acq, clock = make(client, tconfig, on_progress=seen.append)
    acq.hash = "h1"
    done = acq.wait()
    assert done.progress == 1.0 and seen == [10.0, 30.0, 50.0]


@pytest.mark.parametrize("busy", ["moving", "checkingResumeData", "allocating", "metaDL"])
def test_wait_keeps_polling_while_moving_at_full_progress(tconfig, busy):
    seen = []
    client = FakeClient([info(1.0, busy), info(1.0, busy, path="/downloads/tmp/Book"), info(1.0, "stalledUP")])
    acq, clock = make(client, tconfig, on_progress=seen.append)
    acq.hash = "h1"
    done = acq.wait()
    assert done.state == "stalledUP" and client.infos == [] and seen == [50.0, 50.0, 50.0] and clock.t == 10.0


def test_wait_error_state_and_vanished(tconfig):
    acq, _ = make(FakeClient([info(0.1, "error")]), tconfig)
    acq.hash = "h1"
    with pytest.raises(QbtError) as exc:
        acq.wait()
    assert exc.value.code == "torrent_error"
    acq, _ = make(FakeClient([]), tconfig)
    acq.hash = "h1"
    with pytest.raises(QbtError) as exc:
        acq.wait()
    assert exc.value.code == "torrent_error"


def test_wait_stalls_after_configured_hours(tconfig):
    client = FakeClient([info(0.1, downloaded=100)] * 1000)
    acq, clock = make(client, tconfig)  # stall after 1 h, poll every 5 s
    acq.hash = "h1"
    with pytest.raises(QbtError) as exc:
        acq.wait()
    assert exc.value.code == "torrent_stalled" and 3600 <= clock.t <= 3700
    assert client.deleted == []  # cleanup is the caller's job


def test_wait_cancel(tconfig):
    client = FakeClient([info(0.1), info(0.2)])
    acq, clock = make(client, tconfig)
    acq.hash = "h1"
    acq.cancel()
    with pytest.raises(Cancelled):
        acq.wait()


def test_plan_lists_tracks_probes_and_flags_copy(tconfig, tmp_path):
    root = tmp_path / "incoming" / "bookmallow" / "Book"
    root.mkdir(parents=True)
    for n in ("02 - two.m4a", "01 - one.m4a"):
        (root / n).write_bytes(b"x")
    cfg = replace(tconfig, qbt_path_map=f"/downloads:{tmp_path / 'incoming'}")
    probes = []

    def prober(p):
        probes.append(p.name)
        return (30.0, "aac")

    acq, _ = make(FakeClient([]), cfg, prober=prober)
    plan = acq.plan(info(1.0, "uploading", path="/downloads/bookmallow/Book"))
    assert [t.title for t in plan.tracks] == ["01 - one", "02 - two"] and probes == ["01 - one.m4a", "02 - two.m4a"]
    assert plan.tracks[0].location == str(root / "01 - one.m4a") and plan.duration == 60
    assert plan.title == "Book Title" and plan.author == "Idx" and acq.copy_audio is True and acq.single_file is None


def test_plan_mixed_codecs_single_m4b_and_no_audio(tconfig, tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    cfg = replace(tconfig, qbt_path_map=f"/dl:{root}")
    (root / "a.mp3").write_bytes(b"x")
    (root / "b.m4a").write_bytes(b"x")
    codecs = iter([(1.0, "mp3"), (None, "aac")])
    acq, _ = make(FakeClient([]), cfg, prober=lambda p: next(codecs))
    plan = acq.plan(info(1.0, "uploading", path="/dl"))
    assert acq.copy_audio is False and plan.duration == RESULT.duration
    single = root / "only.m4b"
    single.write_bytes(b"x")
    acq, _ = make(FakeClient([]), cfg, prober=lambda p: (5.0, "aac"))
    plan = acq.plan(info(1.0, "uploading", path="/dl/only.m4b"))
    assert acq.single_file == single and len(plan.tracks) == 1
    acq, _ = make(FakeClient([]), cfg)
    with pytest.raises(StoreError) as exc:
        acq.plan(info(1.0, "uploading", path="/dl/missing"))
    assert exc.value.code == "no_audio"


def test_plan_rejects_content_path_outside_path_map(tconfig, tmp_path, caplog):
    (tmp_path / "a.mp3").write_bytes(b"x")  # exists locally, must not be scanned
    probes = []
    acq, _ = make(FakeClient([]), tconfig, prober=lambda p: probes.append(p) or (1.0, "mp3"))
    with pytest.raises(StoreError) as exc:
        acq.plan(info(1.0, "uploading", path=str(tmp_path)))
    assert exc.value.code == "no_audio" and "outside QBT_PATH_MAP" in exc.value.detail and probes == []
    assert "outside QBT_PATH_MAP" in caplog.text


def test_plan_rejects_empty_content_path(tconfig):
    acq, _ = make(FakeClient([]), tconfig)
    with pytest.raises(StoreError) as exc:
        acq.plan(info(1.0, "uploading", path=""))
    assert exc.value.code == "no_audio"


def test_wait_requires_start(tconfig):
    acq, _ = make(FakeClient([]), tconfig)
    with pytest.raises(RuntimeError):
        acq.wait()


def test_cleanup_deletes_with_files_and_swallows_errors(tconfig):
    client = FakeClient([])
    acq, _ = make(client, tconfig)
    acq.cleanup()  # no hash yet → nothing
    acq.hash = "h1"
    acq.cleanup()
    assert client.deleted == [("h1", True)]

    class Angry(FakeClient):
        def delete(self, h, delete_files=True):
            raise QbtError("provider_error", "down")

    acq, _ = make(Angry([]), tconfig)
    acq.hash = "h1"
    acq.cleanup()  # logged, not raised


def test_cleanup_finds_torrent_by_tag_when_hash_never_seen(tconfig):
    client = FakeClient([], find_after=10**6)
    acq, _ = make(client, tconfig, add_timeout=2.0)
    with pytest.raises(QbtError):
        acq.start()
    assert acq.hash is None
    client.find_after = 0  # the tag shows up late
    acq.cleanup()
    assert client.deleted == [("h1", True)]


def test_cleanup_without_add_does_not_query(tconfig):
    class NoCalls(FakeClient):
        def find_by_tag(self, tag):
            raise AssertionError("no torrent was added")

    acq, _ = make(NoCalls([]), tconfig)
    acq.cleanup()


def test_cleanup_tag_lookup_error_is_logged(tconfig):
    class Down(FakeClient):
        def find_by_tag(self, tag):
            raise QbtError("provider_error", "down")

    acq, _ = make(Down([]), tconfig)
    acq._add_sent = True
    acq.cleanup()  # logged, not raised
