"""Process helpers shared by the YouTube converter and the store assembler."""
from __future__ import annotations

import os
import re
import signal
import threading
import time
from collections import deque
from pathlib import Path

_ESCAPE = re.compile(r"([=;#\\\n])")


def escape_ffmetadata(value: str) -> str:
    return _ESCAPE.sub(r"\\\1", value)


class StderrTail(threading.Thread):
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


def terminate_process_groups(procs, grace: float) -> None:
    """SIGTERM every live process group, then SIGKILL whatever survives `grace` seconds."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = [p for p in procs if p.poll() is None]
        if not alive:
            return
        for proc in alive:
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except OSError:
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.05)


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


def unlink_quietly(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def close_quietly(*streams) -> None:
    for stream in streams:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
