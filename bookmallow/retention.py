"""Keep only the newest MAX_FILES MP3s (spec §6.5) and clean up partial files (spec §6.8)."""
from __future__ import annotations

from pathlib import Path

PART_SUFFIX = ".part.mp3"


def list_mp3(directory: Path) -> list[Path]:
    """Finished MP3 files, newest first. Partial files are not MP3s yet."""
    files = [
        p for p in Path(directory).glob("*.mp3")
        if p.is_file() and not p.name.endswith(PART_SUFFIX)
    ]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


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
    removed: list[Path] = []
    for path in Path(directory).glob(f"*{PART_SUFFIX}"):
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed
