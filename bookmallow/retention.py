"""Keep only the newest MAX_FILES MP3s (spec §6.5) and clean up partial files (spec §6.8)."""
from __future__ import annotations

import stat as _stat
from pathlib import Path

PART_SUFFIX = ".part.mp3"


def stat_is_regular(st) -> bool:
    return _stat.S_ISREG(st.st_mode)


def list_mp3(directory: Path) -> list[Path]:
    """Finished MP3 files, newest first. Partial files are not MP3s yet; files that vanish mid-listing are skipped."""
    entries: list[tuple[float, str, Path]] = []
    for path in Path(directory).glob("*.mp3"):
        if path.name.endswith(PART_SUFFIX):
            continue
        try:
            st = path.stat()
        except FileNotFoundError:
            continue
        if not stat_is_regular(st):
            continue
        entries.append((st.st_mtime, path.name, path))
    entries.sort(reverse=True)
    return [path for _, _, path in entries]


def prune(directory: Path, max_files: int) -> list[Path]:
    """Delete every MP3 beyond the newest `max_files`; return what was deleted."""
    deleted: list[Path] = []
    for path in list_mp3(directory)[max_files:]:
        try:
            path.unlink()
            deleted.append(path)
        except FileNotFoundError:
            pass
    return deleted


def next_to_go(directory: Path, max_files: int) -> str | None:
    """Name of the file the next conversion will evict, or None if there is still room."""
    files = list_mp3(directory)
    if len(files) < max_files:
        return None
    return files[-1].name


def remove_partials(directory: Path) -> list[Path]:
    """Remove `.part.mp3` files and their sibling metadata (e.g. `.part.ffmeta`) left by a crash."""
    removed: list[Path] = []
    for path in Path(directory).glob("*.part.*"):
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed
