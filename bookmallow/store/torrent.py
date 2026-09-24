"""Acquire a book through qBittorrent and turn the finished files into a BookPlan (spec §6.4)."""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from ..config import Config
from ..converter import Cancelled
from .models import BookPlan, SearchResult, StoreError, Track, natural_key
from .qbittorrent import QbtClient, QbtError, TorrentInfo

log = logging.getLogger(__name__)
AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".flac", ".wma"}
FINISHED_STATES = {"uploading", "stalledUP", "queuedUP", "pausedUP", "stoppedUP", "forcedUP", "checkingUP"}
ERROR_STATES = {"error", "missingFiles"}
# Not finished even at 100 %: files are being moved out of an incomplete/temp dir, or not checked/allocated yet.
BUSY_STATES = {"moving", "checkingResumeData", "allocating", "metaDL"}
Prober = Callable[[Path], tuple[float | None, str | None]]


def map_path(remote: str, path_map: tuple[str, str]) -> Path | None:
    """Translate a path reported by qBittorrent into the path Bookmallow sees through its read-only mount;
    None when the path is not under the mapped prefix (never scan Bookmallow's own filesystem instead)."""
    src, dst = path_map
    if remote == src or remote.startswith(src.rstrip("/") + "/"):
        return Path(dst + remote[len(src):])
    return None


def list_audio_files(root: Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in AUDIO_EXT else []
    if not root.is_dir():
        return []
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT]
    return sorted(files, key=lambda p: natural_key(str(p.relative_to(root))))


def ffprobe(path: Path, run=subprocess.run) -> tuple[float | None, str | None]:
    """(duration in seconds, audio codec name) via ffprobe; (None, None) when unavailable."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration:stream=codec_name",
           "-of", "json", str(path)]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if proc.returncode != 0:
        return None, None
    try:
        data = json.loads(proc.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        codec = (data.get("streams") or [{}])[0].get("codec_name")
        return (float(duration) if duration else None), (str(codec) if codec else None)
    except (ValueError, AttributeError, IndexError):
        return None, None


class TorrentAcquisition:
    """add → wait → plan → (assembly by the caller) → cleanup. `cancel()` may be called from any thread."""

    def __init__(self, client: QbtClient, result: SearchResult, config: Config, job_id: str,
                 on_progress: Callable[[float], None] | None = None, *, sleep=time.sleep, clock=time.monotonic,
                 prober: Prober = ffprobe, poll_interval: float = 5.0, add_timeout: float = 30.0):
        self.client, self.result, self.config, self.job_id = client, result, config, job_id
        self._on_progress = on_progress or (lambda p: None)
        self._sleep, self._clock, self._prober = sleep, clock, prober
        self._poll, self._add_timeout = poll_interval, add_timeout
        self._cancelled = threading.Event()
        self.hash: str | None = None
        self._add_sent = False  # add() was sent: qBittorrent may hold the torrent even if we never saw its hash
        self.copy_audio = False
        self.single_file: Path | None = None

    def cancel(self) -> None:
        self._cancelled.set()

    def start(self) -> str:
        if not self.result.download:
            raise QbtError("torrent_add", "this result has no download link")
        self.client.login()
        self.client.ensure_category(self.config.qbt_category)
        tag = f"job-{self.job_id}"
        self._add_sent = True
        self.client.add(self.result.download, self.config.qbt_category, ["bookmallow", tag])
        deadline = self._clock() + self._add_timeout
        while self._clock() < deadline:
            if self._cancelled.is_set():
                raise Cancelled()
            found = self.client.find_by_tag(tag)
            if found is not None:
                self.hash = found.hash
                return found.hash
            self._sleep(1.0)
        raise QbtError("torrent_add", "the torrent did not appear in qBittorrent")

    def wait(self) -> TorrentInfo:
        if not self.hash:
            raise RuntimeError("TorrentAcquisition.wait() called before start()")
        last_bytes, last_change = -1, self._clock()
        stall_after = self.config.torrent_stall_hours * 3600
        while True:
            if self._cancelled.is_set():
                raise Cancelled()
            info = self.client.info(self.hash)
            if info is None:
                raise QbtError("torrent_error", "the torrent vanished from qBittorrent")
            if info.state in ERROR_STATES:
                raise QbtError("torrent_error", f"qBittorrent state {info.state}")
            if info.state not in BUSY_STATES and (info.progress >= 1.0 or info.state in FINISHED_STATES):
                self._on_progress(50.0)
                return info
            now = self._clock()
            if info.downloaded != last_bytes:
                last_bytes, last_change = info.downloaded, now
            elif now - last_change > stall_after:
                raise QbtError("torrent_stalled", f"no data for {self.config.torrent_stall_hours:g} h")
            self._on_progress(round(info.progress * 50, 1))
            self._sleep(self._poll)

    def plan(self, info: TorrentInfo) -> BookPlan:
        if not info.content_path:
            raise StoreError("no_audio", "qBittorrent reported no content path for this torrent")
        local = map_path(info.content_path, self.config.path_map)
        if local is None:
            log.warning("torrent content path %s is outside QBT_PATH_MAP (%s)", info.content_path, self.config.qbt_path_map)
            raise StoreError("no_audio", f"content path {info.content_path} is outside QBT_PATH_MAP")
        files = list_audio_files(local)
        if not files:
            raise StoreError("no_audio", f"no audio files under {local}")
        if len(files) == 1 and files[0].suffix.lower() == ".m4b":
            self.single_file = files[0]
        tracks, codecs = [], []
        for path in files:
            duration, codec = self._prober(path)
            codecs.append(codec)
            tracks.append(Track(location=str(path), duration=duration, title=path.stem))
        self.copy_audio = bool(codecs) and all(c == "aac" for c in codecs)
        duration = int(round(sum(t.duration for t in tracks))) if all(t.duration is not None for t in tracks) else self.result.duration
        return BookPlan(title=self.result.title, author=self.result.author, language=self.result.language,
                        duration=duration, cover=None, tracks=tracks)

    def cleanup(self) -> None:
        torrent_hash = self.hash
        try:
            if not torrent_hash and self._add_sent:
                # add() may have succeeded while the tag never showed up within add_timeout: look once more.
                found = self.client.find_by_tag(f"job-{self.job_id}")
                torrent_hash = found.hash if found is not None else None
            if not torrent_hash:
                return
            self.client.delete(torrent_hash, delete_files=True)
        except StoreError as exc:
            log.warning("could not delete torrent %s: %s", torrent_hash or f"tagged job-{self.job_id}", exc.detail)
