"""Data shapes shared by the store providers, the search layer and the acquisition pipelines (spec §5)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_LANG_CODES = {
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr", "français": "fr", "francais": "fr",
    "en": "en", "eng": "en", "english": "en",
    "de": "de", "ger": "de", "deu": "de", "german": "de",
    "es": "es", "spa": "es", "spanish": "es",
    "it": "it", "ita": "it", "italian": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt",
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "la": "la", "lat": "la", "latin": "la",
    "mul": "mul", "multilingual": "mul",
}
_RUNTIME = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)\s*$")


class StoreError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class Track:
    location: str  # http(s) URL or local path
    duration: float | None = None
    title: str = ""


@dataclass
class BookPlan:
    title: str
    author: str | None
    language: str | None
    duration: int | None
    cover: str | None
    tracks: list[Track] = field(default_factory=list)


@dataclass
class SearchResult:
    source: str
    source_id: str
    title: str
    author: str | None = None
    language: str | None = None
    duration: int | None = None
    size_bytes: int | None = None
    seeders: int | None = None
    cover: str | None = None
    url: str | None = None
    download: str | None = None  # magnet / .torrent URL, never sent to the browser
    alt_ids: list[str] = field(default_factory=list)  # e.g. the Internet Archive id of a LibriVox book

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def public(self) -> dict:
        data = asdict(self)
        data.pop("download")
        data["key"] = self.key
        return data


def lang_code(value: str | None) -> str | None:
    if not value:
        return None
    return _LANG_CODES.get(str(value).strip().lower())


def parse_runtime(text: str | None) -> int | None:
    """'39:33:23', '40:46', '789.52' or '12' → whole seconds; None when unreadable."""
    if text is None:
        return None
    m = _RUNTIME.match(str(text))
    if not m:
        return None
    h, mn, s = m.groups()
    parts = [p for p in (h, mn) if p is not None]  # "40:46" → parts == ["40"] (minutes); "1:02:03" → ["1", "02"]
    total = float(s)
    if len(parts) == 1:
        total += int(parts[0]) * 60
    elif len(parts) == 2:
        total += int(parts[0]) * 3600 + int(parts[1]) * 60
    return int(round(total))
