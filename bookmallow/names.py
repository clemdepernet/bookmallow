"""Turn video titles into safe, unique file names."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")
FALLBACK = "audiobook"


def safe_filename(title: str | None, video_id: str, ext: str = ".mp3", max_len: int = 120) -> str:
    """`<title> [<video_id>]<ext>`, stripped of characters that upset any OS."""
    base = unicodedata.normalize("NFC", title or "")
    base = _FORBIDDEN.sub("", base)
    base = _SPACES.sub(" ", base).strip(" .")
    suffix = f" [{video_id}]{ext}"
    room = max(max_len - len(suffix), 1)
    if len(base) > room:
        base = base[:room].rstrip(" .")
    if not base:
        base = FALLBACK
    return f"{base}{suffix}"


def unique_name(name: str, existing: Iterable[str]) -> str:
    """Append ` (2)`, ` (3)`… before the extension until the name is free."""
    taken = set(existing)
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem} ({n}){dot}{ext}"
        if candidate not in taken:
            return candidate
        n += 1
