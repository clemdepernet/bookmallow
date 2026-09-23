"""Parse and validate YouTube links. Anything else is refused (spec §2, §6.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

ALLOWED_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
})
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,}$")
_PATH_ID = re.compile(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})(?:[/?]|$)")


class InvalidUrl(ValueError):
    """The text is not a usable YouTube video or playlist link."""


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class ParsedUrl:
    video_id: str | None
    playlist_id: str | None

    @property
    def is_playlist(self) -> bool:
        return self.playlist_id is not None

    @property
    def watch_url(self) -> str:
        if self.video_id is None:
            raise InvalidUrl("no video id")
        return watch_url(self.video_id)

    @property
    def playlist_url(self) -> str:
        if self.playlist_id is None:
            raise InvalidUrl("no playlist id")
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"


def parse(raw: str) -> ParsedUrl:
    text = (raw or "").strip()
    if not text:
        raise InvalidUrl("empty")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise InvalidUrl("not_youtube")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidUrl("not_youtube")

    query = parse_qs(parts.query)
    video_id: str | None = None
    playlist_id: str | None = None

    if host.endswith("youtu.be"):
        candidate = parts.path.strip("/").split("/")[0]
        if _VIDEO_ID.match(candidate):
            video_id = candidate
    else:
        v = query.get("v", [""])[0]
        if _VIDEO_ID.match(v):
            video_id = v
        else:
            m = _PATH_ID.match(parts.path)
            if m:
                video_id = m.group(1)

    lst = query.get("list", [""])[0]
    if lst and not lst.startswith(("RD", "UL")) and _PLAYLIST_ID.match(lst):
        playlist_id = lst

    if video_id is None and playlist_id is None:
        raise InvalidUrl("no_id")
    return ParsedUrl(video_id=video_id, playlist_id=playlist_id)
