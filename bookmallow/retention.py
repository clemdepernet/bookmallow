"""Keep only the newest MAX_FILES audio files (spec §6.5) and clean up partial files (spec §6.8)."""
from __future__ import annotations

import stat as _stat
from pathlib import Path

AUDIO_SUFFIXES = (".mp3", ".m4b")
PART_MARK = ".part."
PART_SUFFIX = ".part.mp3"  # historical name, still used by converter tests


def stat_is_regular(st) -> bool:
    return _stat.S_ISREG(st.st_mode)


def is_partial(name: str) -> bool:
    return PART_MARK in name


def part_path(out_path: Path) -> Path:
    """`Title.m4b` → `Title.part.m4b`: the file being written, ignored by retention."""
    return out_path.with_name(out_path.stem + ".part" + out_path.suffix)


def list_audio(directory: Path) -> list[Path]:
    """Finished MP3/M4B files, newest first. Partial files are skipped, as are files that vanish mid-listing."""
    entries: list[tuple[float, str, Path]] = []
    for path in Path(directory).iterdir():
        if path.suffix.lower() not in AUDIO_SUFFIXES or is_partial(path.name):
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


list_mp3 = list_audio


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
