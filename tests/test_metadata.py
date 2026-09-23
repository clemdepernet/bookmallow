from __future__ import annotations

import json

import pytest

from bookmallow import metadata as md

VIDEO_JSON = {
    "id": "dQw4w9WgXcQ", "title": "Un livre", "duration": 36000.0, "thumbnail": "https://i.ytimg.com/x.jpg",
    "channel": "La Chaîne", "uploader": "uploader-name",
    "chapters": [{"title": "Ch 1", "start_time": 0, "end_time": 600.5}, {"title": "Ch 2", "start_time": 600.5, "end_time": 36000}],
}


def runner_returning(payload):
    calls = []

    def runner(args, timeout):
        calls.append((args, timeout))
        return json.dumps(payload)

    runner.calls = calls
    return runner


def test_fetch_video_maps_fields():
    runner = runner_returning(VIDEO_JSON)
    meta = md.fetch_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ", runner=runner)
    assert meta.video_id == "dQw4w9WgXcQ"
    assert meta.title == "Un livre"
    assert meta.duration == 36000
    assert meta.thumbnail == "https://i.ytimg.com/x.jpg"
    assert meta.channel == "La Chaîne"
    assert meta.chapters == [{"title": "Ch 1", "start": 0.0, "end": 600.5}, {"title": "Ch 2", "start": 600.5, "end": 36000.0}]
    args, timeout = runner.calls[0]
    assert "--dump-single-json" in args and "--no-playlist" in args and args[-1].endswith("dQw4w9WgXcQ")
    assert timeout == 60.0


def test_fetch_video_falls_back_to_uploader_and_no_duration():
    payload = {**VIDEO_JSON, "channel": None, "duration": None, "chapters": None}
    meta = md.fetch_video("u", runner=runner_returning(payload))
    assert meta.channel == "uploader-name"
    assert meta.duration is None
    assert meta.chapters == []


def test_fetch_video_refuses_live():
    with pytest.raises(md.MetadataError) as exc:
        md.fetch_video("u", runner=runner_returning({**VIDEO_JSON, "is_live": True}))
    assert exc.value.code == "live"


def test_fetch_video_unreadable_json():
    with pytest.raises(md.MetadataError) as exc:
        md.fetch_video("u", runner=lambda a, t: "not json")
    assert exc.value.code == "metadata"


def test_fetch_playlist():
    payload = {"id": "PLxyz", "title": "Ma liste", "entries": [
        {"id": "aaaaaaaaaaa", "title": "Part 1", "duration": 100},
        None,
        {"id": "bbbbbbbbbbb", "title": None, "duration": None},
        {"title": "no id"},
    ]}
    runner = runner_returning(payload)
    pl = md.fetch_playlist("https://www.youtube.com/playlist?list=PLxyz", runner=runner)
    assert pl.playlist_id == "PLxyz" and pl.title == "Ma liste"
    assert [(e.video_id, e.title, e.duration) for e in pl.entries] == [
        ("aaaaaaaaaaa", "Part 1", 100), ("bbbbbbbbbbb", "Sans titre", None)]
    assert "--flat-playlist" in runner.calls[0][0]


def test_fetch_playlist_bounds_the_preview_with_playlist_items(monkeypatch):
    runner = runner_returning({"id": "PLxyz", "title": "Ma liste", "entries": []})
    md.fetch_playlist("https://www.youtube.com/playlist?list=PLxyz", runner=runner, limit=200)
    args = runner.calls[0][0]
    assert "--playlist-items" in args
    assert args[args.index("--playlist-items") + 1] == ":200"


@pytest.mark.parametrize("stderr,code", [
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [youtube] abc: Sign in to confirm your age", "age"),
    ("ERROR: The uploader has not made this video available in your country", "geo"),
    ("ERROR: [youtube] abc: Video unavailable", "unavailable"),
    ("ERROR: [youtube] X: This video is unavailable", "unavailable"),
    ("ERROR: [youtube] X: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies", "bot"),
    ("WARNING: something\nERROR: This live event will begin in 3 hours", "live"),
    ("ERROR: something new and weird", "ytdlp"),
])
def test_classify_error(stderr, code):
    got_code, detail = md.classify_error(stderr)
    assert got_code == code
    assert detail == stderr.splitlines()[-1].strip()


def test_default_runner_raises_when_binary_missing(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise FileNotFoundError("yt-dlp")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(md.MetadataError) as exc:
        md.default_runner(["--version"], 5)
    assert exc.value.code == "ytdlp"


def test_default_runner_maps_nonzero_exit(monkeypatch):
    import subprocess

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Private video"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(md.MetadataError) as exc:
        md.default_runner(["x"], 5)
    assert exc.value.code == "private"


def test_fetch_video_raises_metadata_error_on_null_json(monkeypatch):
    """yt-dlp exiting 0 while printing `null` (seen in the wild) must not crash fetch_video (finding #6)."""
    import subprocess

    class Proc:
        returncode = 0
        stdout = "null\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(md.MetadataError) as exc:
        md.fetch_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert exc.value.code == "metadata"
