"""Fetch video / playlist metadata with `yt-dlp --dump-single-json` (spec §4, §11)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable

Runner = Callable[[list[str], float], str]

_COMMON = ["--no-warnings", "--no-progress", "--dump-single-json"]
_ERROR_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("private", ("private video",)),
    ("age", ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users")),
    ("bot", ("not a bot", "sign in to confirm you")),
    ("geo", ("available in your country", "geo restricted", "geo-restricted", "blocked it in your country")),
    ("unavailable", ("video unavailable", "is unavailable", "has been removed", "no longer available",
                      "does not exist", "video is not available")),
    ("live", ("live event", "premieres in", "is a live stream", "live stream")),
]


class MetadataError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class VideoMeta:
    video_id: str
    title: str
    duration: int | None
    thumbnail: str | None
    channel: str | None
    chapters: list[dict] = field(default_factory=list)


@dataclass
class PlaylistEntry:
    video_id: str
    title: str
    duration: int | None


@dataclass
class PlaylistMeta:
    playlist_id: str
    title: str
    entries: list[PlaylistEntry]


def last_line(text: str, limit: int = 200) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else "")[:limit]


def classify_error(stderr: str) -> tuple[str, str]:
    """Map yt-dlp's stderr to a short error code plus its last line."""
    text = stderr.lower()
    for code, needles in _ERROR_PATTERNS:
        if any(needle in text for needle in needles):
            return code, last_line(stderr)
    return "ytdlp", last_line(stderr)


def default_runner(args: list[str], timeout: float) -> str:
    try:
        proc = subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise MetadataError("ytdlp", "yt-dlp is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MetadataError("timeout", f"yt-dlp took more than {int(timeout)} s") from exc
    if proc.returncode != 0:
        code, detail = classify_error(proc.stderr)
        raise MetadataError(code, detail or f"yt-dlp exited with {proc.returncode}")
    return proc.stdout


def _parse(out: str) -> dict:
    try:
        info = json.loads(out)
    except ValueError as exc:
        raise MetadataError("metadata", "yt-dlp returned unreadable metadata") from exc
    if not isinstance(info, dict):
        raise MetadataError("metadata", "yt-dlp returned unexpected metadata")
    return info


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def fetch_video(url: str, runner: Runner = default_runner, timeout: float = 60.0) -> VideoMeta:
    info = _parse(runner([*_COMMON, "--no-playlist", url], timeout))
    if info.get("is_live"):
        raise MetadataError("live", "live streams cannot be converted")
    chapters = [
        {"title": str(c.get("title") or ""), "start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0)}
        for c in (info.get("chapters") or []) if isinstance(c, dict)
    ]
    return VideoMeta(
        video_id=str(info.get("id") or ""),
        title=str(info.get("title") or "Sans titre"),
        duration=_int_or_none(info.get("duration")),
        thumbnail=info.get("thumbnail"),
        channel=info.get("channel") or info.get("uploader"),
        chapters=chapters,
    )


def fetch_playlist(url: str, runner: Runner = default_runner, timeout: float = 90.0, limit: int = 200) -> PlaylistMeta:
    info = _parse(runner([*_COMMON, "--flat-playlist", "--playlist-items", f":{limit}", url], timeout))
    entries = [
        PlaylistEntry(video_id=str(e["id"]), title=str(e.get("title") or "Sans titre"), duration=_int_or_none(e.get("duration")))
        for e in (info.get("entries") or []) if isinstance(e, dict) and e.get("id")
    ]
    return PlaylistMeta(playlist_id=str(info.get("id") or ""), title=str(info.get("title") or "Playlist"), entries=entries)
