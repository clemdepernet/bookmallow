"""Assemble chapter tracks (URLs or local files) into one M4B with chapters and cover art (spec §6.3, §6.4)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..converter import Cancelled, ConversionError
from ..metadata import last_line
from ..procutil import (StderrTail, close_quietly, escape_ffmetadata, parse_progress_line, progress_percent,
                        terminate_process_groups, unlink_quietly)
from ..retention import part_path
from .http import get_bytes
from .models import StoreError, Track

log = logging.getLogger(__name__)
PROTOCOLS = "file,http,https,tcp,tls,crypto"
# ffconcat `option` lines for remote tracks: a read timeout (no hang on a half-open connection) and reconnects
# on network errors, 429 and 5xx (a transient archive.org 503 must not kill a 10-hour book).
HTTP_OPTIONS = (("rw_timeout", "30000000"), ("reconnect", "1"), ("reconnect_on_network_error", "1"),
                ("reconnect_on_http_error", "429,5xx"), ("reconnect_delay_max", "60"))
_COVER_NAMES = {"image/jpeg": "cover.jpg", "image/jpg": "cover.jpg", "image/png": "cover.png"}


@dataclass
class AssembleRequest:
    tracks: list[Track]
    out_path: Path
    work_dir: Path
    title: str
    author: str | None = None
    language: str | None = None
    duration: int | None = None
    cover: str | None = None  # URL, or a local path when the cover came with a torrent
    bitrate: str = "64k"
    copy_audio: bool = False
    source_url: str | None = None

    @property
    def part_path(self) -> Path:
        return part_path(self.out_path)

    @property
    def cover_part_path(self) -> Path:
        """Output of the cover remux pass; still a partial file for retention and startup cleanup."""
        return self.out_path.with_name(self.out_path.stem + ".part.cover" + self.out_path.suffix)


def concat_list(tracks: list[Track]) -> str:
    lines = ["ffconcat version 1.0"]
    for t in tracks:
        lines.append("file '" + t.location.replace("'", "'\\''") + "'")
        if t.location.lower().startswith(("http://", "https://")):
            lines += [f"option {name} {value}" for name, value in HTTP_OPTIONS]
    return "\n".join(lines) + "\n"


def chapters_from_tracks(tracks: list[Track]) -> list[dict]:
    if not tracks or any(t.duration is None for t in tracks):
        return []
    chapters, start = [], 0.0
    for i, t in enumerate(tracks, 1):
        end = start + float(t.duration)
        chapters.append({"title": t.title or f"Chapter {i}", "start": start, "end": end})
        start = end
    return chapters


def ffmetadata(req: AssembleRequest) -> str:
    tags = {"title": req.title, "album": req.title, "genre": "Audiobook"}
    if req.author:
        tags["artist"] = req.author
        tags["album_artist"] = req.author
    if req.source_url:
        tags["comment"] = req.source_url
    lines = [";FFMETADATA1"] + [f"{k}={escape_ffmetadata(v)}" for k, v in tags.items()]
    for ch in chapters_from_tracks(req.tracks):
        start, end = int(round(ch["start"] * 1000)), int(round(ch["end"] * 1000))
        if end <= start:
            continue
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={escape_ffmetadata(ch['title'])}"]
    return "\n".join(lines) + "\n"


def ffmpeg_command(req: AssembleRequest, list_path: Path, meta_path: Path) -> list[str]:
    """Pass 1: audio + metadata + chapters, no cover. A cover stream here would pin ffmpeg's `-progress`
    to its single frame (the minimum across streams), so it is added by a separate remux pass."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-protocol_whitelist", PROTOCOLS, "-f", "concat", "-safe", "0", "-i", str(list_path),
           "-i", str(meta_path), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
    if req.copy_audio:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", req.bitrate, "-ac", "1"]
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-y", "-f", "ipod", str(req.part_path)]
    return cmd


def remux_cover_command(part: Path, cover_path: Path, out_path: Path) -> list[str]:
    """Pass 2: copy the pass-1 audio (chapters and tags follow) and attach the cover, no re-encoding.
    Only `0:a` is mapped: the chapter text track of pass 1 reads back as a data stream the ipod muxer refuses."""
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(part), "-i", str(cover_path),
            "-map", "0:a", "-map", "1:v", "-c", "copy", "-disposition:v", "attached_pic",
            "-movflags", "+faststart", "-y", "-f", "ipod", str(out_path)]


def cover_filename(content_type: str | None) -> str | None:
    return _COVER_NAMES.get((content_type or "").lower())


class Assembly:
    """Produce the final M4B: one encoding ffmpeg run, plus a quick cover remux when there is a cover.
    `run()` blocks; `cancel()` may be called from any thread."""

    def __init__(self, req: AssembleRequest, on_progress: Callable[[float], None] | None = None,
                 popen=subprocess.Popen, kill_grace: float = 5.0, fetch_bytes=get_bytes):
        self.req = req
        self._on_progress = on_progress or (lambda percent: None)
        self._popen = popen
        self._kill_grace = kill_grace
        self._fetch_bytes = fetch_bytes
        self._procs: list = []
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            procs = list(self._procs)
        terminate_process_groups(procs, self._kill_grace)

    def _cover_path(self, work: Path) -> Path | None:
        cover = self.req.cover
        if not cover:
            return None
        if "://" not in cover:
            local = Path(cover)
            return local if local.is_file() else None
        if self._fetch_bytes is None:
            return None
        try:
            body, ctype = self._fetch_bytes(cover, timeout=10.0)
        except StoreError as exc:
            log.warning("cover download failed (%s), continuing without cover", exc.detail)
            return None
        name = cover_filename(ctype) or ("cover.jpg" if body[:3] == b"\xff\xd8\xff" else None)
        if name is None:
            return None
        path = work / name
        path.write_bytes(body)
        return path

    def _ffmpeg(self, cmd: list[str], report: bool) -> None:
        proc = self._popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            with self._lock:
                self._procs = [proc]
            if self._cancelled.is_set():
                terminate_process_groups([proc], self._kill_grace)
            tail = StderrTail(proc.stderr)
            for raw in proc.stdout:
                us = parse_progress_line(raw.decode("utf-8", "replace"))
                if report and us is not None:
                    self._on_progress(progress_percent(us, self.req.duration))
            rc = proc.wait()
            tail.join(timeout=2)
            if self._cancelled.is_set():
                raise Cancelled()
            if rc != 0:
                text = tail.text()
                raise ConversionError("ffmpeg", last_line(text) or f"ffmpeg exited with {rc}", tail=text)
        finally:
            with self._lock:
                self._procs = []
            close_quietly(proc.stdout, proc.stderr)

    def run(self) -> None:
        req = self.req
        work = req.work_dir
        work.mkdir(parents=True, exist_ok=True)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self._cancelled.is_set():
                raise Cancelled()
            list_path, meta_path = work / "list.txt", work / "meta.ffm"
            list_path.write_text(concat_list(req.tracks), encoding="utf-8")
            meta_path.write_text(ffmetadata(req), encoding="utf-8")
            cover_path = self._cover_path(work)

            self._ffmpeg(ffmpeg_command(req, list_path, meta_path), report=True)
            if cover_path is not None:
                if self._cancelled.is_set():
                    raise Cancelled()
                self._ffmpeg(remux_cover_command(req.part_path, cover_path, req.cover_part_path), report=False)
                os.replace(req.cover_part_path, req.part_path)
            os.replace(req.part_path, req.out_path)
        except BaseException:
            unlink_quietly(req.part_path)
            unlink_quietly(req.cover_part_path)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
