"""Stream a video's audio through ffmpeg into an MP3 without an intermediate file (spec §6.3)."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import QUALITIES
from .metadata import classify_error, last_line
from .retention import PART_SUFFIX

YTDLP_FORMAT = "bestaudio[ext=webm]/bestaudio[acodec^=opus]/bestaudio/best"
_ESCAPE = re.compile(r"([=;#\\\n])")


class ConversionError(Exception):
    def __init__(self, code: str, detail: str = "", tail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.tail = tail


class Cancelled(Exception):
    """The conversion was cancelled by the user."""


@dataclass
class ConvertRequest:
    url: str
    quality: str
    out_path: Path
    duration: int | None = None
    title: str | None = None
    channel: str | None = None
    chapters: list[dict] = field(default_factory=list)

    @property
    def part_path(self) -> Path:
        name = self.out_path.name
        stem = name[:-4] if name.endswith(".mp3") else name
        return self.out_path.with_name(stem + PART_SUFFIX)


def ytdlp_command(url: str) -> list[str]:
    return ["yt-dlp", "--no-playlist", "--no-warnings", "--no-progress", "--quiet",
            "-f", YTDLP_FORMAT, "-o", "-", url]


def _tags(req: ConvertRequest) -> dict[str, str]:
    tags = {"comment": req.url}
    if req.title:
        tags["title"] = req.title
    if req.channel:
        tags["artist"] = req.channel
        tags["album_artist"] = req.channel
    return tags


def ffmpeg_command(req: ConvertRequest, meta_path: Path | None) -> list[str]:
    q = QUALITIES[req.quality]
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0"]
    if meta_path is not None:
        cmd += ["-i", str(meta_path), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
    else:
        cmd += ["-map", "0:a"]
        for key, value in _tags(req).items():
            cmd += ["-metadata", f"{key}={value}"]
    cmd += ["-vn", "-ac", str(q["channels"]), "-codec:a", "libmp3lame", "-b:a", q["bitrate"],
            "-id3v2_version", "3", "-progress", "pipe:1", "-nostats", "-y", "-f", "mp3", str(req.part_path)]
    return cmd


def _escape(value: str) -> str:
    return _ESCAPE.sub(r"\\\1", value)


def write_ffmetadata(req: ConvertRequest) -> str:
    lines = [";FFMETADATA1"]
    for key, value in _tags(req).items():
        lines.append(f"{key}={_escape(value)}")
    for ch in req.chapters:
        start = int(round(float(ch.get("start", 0)) * 1000))
        end = int(round(float(ch.get("end", 0)) * 1000))
        if end <= start:
            continue
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_escape(str(ch.get('title') or ''))}"]
    return "\n".join(lines) + "\n"


def parse_progress_line(line: str) -> int | None:
    """Microseconds converted so far, from one `ffmpeg -progress` line; None for other keys."""
    key, sep, value = line.strip().partition("=")
    if not sep or key not in ("out_time_us", "out_time_ms"):
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        return None


def progress_percent(out_time_us: int, duration: int | None) -> float:
    if not duration:
        return 0.0
    return round(min(out_time_us / (duration * 1_000_000) * 100.0, 99.9), 1)


class _Tail(threading.Thread):
    """Drain a stderr pipe in the background, keeping the last few lines."""

    def __init__(self, stream, keep: int = 20):
        super().__init__(daemon=True)
        self._stream = stream
        self._lines: deque[str] = deque(maxlen=keep)
        self.start()

    def run(self) -> None:
        for raw in self._stream:
            self._lines.append(raw.decode("utf-8", "replace").rstrip())

    def text(self) -> str:
        return "\n".join(self._lines)


def _terminate(procs, grace: float) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = [p for p in procs if p.poll() is None]
        if not alive:
            return
        for proc in alive:
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.05)


def _unlink(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


class Conversion:
    """One yt-dlp → ffmpeg pipeline. `run()` blocks; `cancel()` may be called from any thread."""

    def __init__(self, req: ConvertRequest, on_progress: Callable[[float], None] | None = None,
                 popen=subprocess.Popen, kill_grace: float = 5.0):
        self.req = req
        self._on_progress = on_progress or (lambda percent: None)
        self._popen = popen
        self._kill_grace = kill_grace
        self._procs: list = []
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            procs = list(self._procs)
        _terminate(procs, self._kill_grace)

    def run(self) -> None:
        req = self.req
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path: Path | None = None
        yt = ff = None
        try:
            if self._cancelled.is_set():
                raise Cancelled()
            if req.chapters:
                meta_path = req.part_path.with_suffix(".ffmeta")
                meta_path.write_text(write_ffmetadata(req), encoding="utf-8")

            yt = self._popen(ytdlp_command(req.url), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            ff = self._popen(ffmpeg_command(req, meta_path), stdin=yt.stdout, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
            yt.stdout.close()  # ffmpeg now owns the read end; yt-dlp gets EPIPE if ffmpeg dies
            with self._lock:
                self._procs = [yt, ff]
            if self._cancelled.is_set():
                _terminate([yt, ff], self._kill_grace)

            yt_err, ff_err = _Tail(yt.stderr), _Tail(ff.stderr)
            for raw in ff.stdout:
                us = parse_progress_line(raw.decode("utf-8", "replace"))
                if us is not None:
                    self._on_progress(progress_percent(us, req.duration))
            ff_rc, yt_rc = ff.wait(), yt.wait()
            yt_err.join(timeout=2)
            ff_err.join(timeout=2)

            if self._cancelled.is_set():
                raise Cancelled()
            yt_text = yt_err.text()
            if yt_rc != 0 and "ERROR:" in yt_text and "Broken pipe" not in yt_text:
                code, detail = classify_error(yt_text)
                raise ConversionError(code, detail or f"yt-dlp exited with {yt_rc}", tail=yt_text)
            if ff_rc != 0:
                tail = ff_err.text()
                raise ConversionError("ffmpeg", last_line(tail) or f"ffmpeg exited with {ff_rc}", tail=tail)
            if yt_rc != 0:
                code, detail = classify_error(yt_text)
                raise ConversionError(code, detail or f"yt-dlp exited with {yt_rc}", tail=yt_text)
            os.replace(req.part_path, req.out_path)
        except BaseException:
            _unlink(req.part_path)
            raise
        finally:
            if meta_path is not None:
                _unlink(meta_path)
            if ff is not None:
                ff.stdout.close()
                ff.stderr.close()
            if yt is not None:
                yt.stderr.close()
