"""Internet Archive: complements LibriVox with other free audiobook collections (spec §6.1, §6.3)."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import quote

from ..http import get_json
from ..models import BookPlan, SearchResult, StoreError, Track, lang_code, natural_key, parse_runtime

SEARCH = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
DOWNLOAD = "https://archive.org/download/"
IMG = "https://archive.org/services/img/"
COLLECTIONS = "(collection:librivoxaudio OR collection:audio_bookspoetry)"
LANG_QUERY = {"fr": "(fre OR fra OR french)", "en": "(eng OR english)"}
FIELDS = ["identifier", "title", "creator", "language", "runtime"]
_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')
_BITRATE = re.compile(r"_(\d{2,3}kb|vbr)$", re.I)
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # no leading dot: ".." must not climb the URL path
Fetch = Callable[..., object]


def escape_lucene(text: str) -> str:
    return _LUCENE.sub(r"\\\1", text)


def _first(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value).strip() if value not in (None, "") else None


def _result(doc: dict) -> SearchResult:
    ident = str(doc.get("identifier") or "")
    return SearchResult(
        source="archive",
        source_id=ident,
        title=_first(doc.get("title")) or ident,
        author=_first(doc.get("creator")),
        language=lang_code(_first(doc.get("language"))),
        duration=parse_runtime(_first(doc.get("runtime"))),
        cover=f"{IMG}{ident}",
        url=f"https://archive.org/details/{ident}",
    )


def search(q: str, lang: str, fetch: Fetch = get_json, timeout: float = 20.0, limit: int = 25) -> list[SearchResult]:
    term = escape_lucene(q)
    query = f"{COLLECTIONS} AND (title:({term}) OR creator:({term}))"
    if lang in LANG_QUERY:
        query += f" AND language:{LANG_QUERY[lang]}"
    payload = fetch(SEARCH, {"q": query, "fl[]": FIELDS, "rows": str(limit), "output": "json"}, timeout=timeout)
    docs = payload.get("response", {}).get("docs", []) if isinstance(payload, dict) else []
    return [_result(d) for d in docs if isinstance(d, dict) and d.get("identifier")]


def _track_key(name: str) -> str:
    stem = name[:-4]
    return _BITRATE.sub("", stem)


def _track_number(f: dict) -> int | None:
    head = str(f.get("track") or "").split("/")[0].strip()
    return int(head) if head.isdigit() else None


def pick_tracks(files: list[dict]) -> list[dict]:
    """One MP3 per chapter: prefer the `_64kb` derivative, then the original, then anything.

    Ordered by the `track` field only when every picked file has a numeric one (on real items it is often
    inherited by just a few derivatives), otherwise by a natural sort of the chapter name."""
    groups: dict[str, list[dict]] = {}
    for f in files:
        name = str(f.get("name") or "")
        if not name.lower().endswith(".mp3"):
            continue
        groups.setdefault(_track_key(name), []).append(f)

    def rank(f: dict) -> int:
        n = str(f["name"]).lower()
        return 0 if n.endswith("_64kb.mp3") else (1 if f.get("source") == "original" else 2)

    chosen = [sorted(g, key=rank)[0] for g in groups.values()]
    by_track = bool(chosen) and all(_track_number(f) is not None for f in chosen)

    def order(f: dict):
        name_key = natural_key(_track_key(str(f["name"])))
        return (_track_number(f), name_key) if by_track else (0, name_key)

    return sorted(chosen, key=order)


def pick_cover(identifier: str, files: list[dict]) -> str:
    """A real cover image: names saying so first, then an original JPEG/PNG, else the item tile service."""
    images = []
    for f in files:
        name = str(f.get("name") or "")
        low = name.lower()
        if not low.endswith((".jpg", ".jpeg", ".png")) or low.startswith("__ia_thumb") or "spectrogram" in low:
            continue
        if low.rsplit(".", 1)[0].endswith("_thumb"):
            continue
        images.append((name, f.get("source") == "original"))
    preferred = [n for n, _ in images if any(k in n.lower() for k in ("itemimage", "cover", "front"))]
    originals = [n for n, original in images if original]
    for candidates in (preferred, originals):
        if candidates:
            return f"{DOWNLOAD}{quote(identifier, safe='')}/{quote(candidates[0])}"
    return f"{IMG}{quote(identifier, safe='')}"


def _duration(raw) -> float | None:
    if isinstance(raw, str) and re.fullmatch(r"\d+(\.\d+)?", raw):
        return float(raw)
    length = parse_runtime(raw)
    return float(length) if length is not None else None


def plan(identifier: str, fetch: Fetch = get_json, timeout: float = 20.0) -> BookPlan:
    if not _IDENT.fullmatch(identifier or ""):
        raise StoreError("not_found", "invalid Internet Archive identifier")
    ident = quote(identifier, safe="")
    payload = fetch(f"{META}{ident}", None, timeout=timeout)
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata"), dict):
        raise StoreError("not_found", f"Internet Archive item {identifier} not found")
    meta = payload["metadata"]
    files = [f for f in (payload.get("files") or []) if isinstance(f, dict)]
    picked = pick_tracks(files)
    if not picked:
        raise StoreError("no_tracks", "this item has no MP3 files")
    tracks = []
    for f in picked:
        name = str(f["name"])
        title = _first(f.get("title")) or name[:-4]
        tracks.append(Track(location=f"{DOWNLOAD}{ident}/{quote(name)}", duration=_duration(f.get("length")), title=title))
    cover = pick_cover(identifier, files)
    duration = parse_runtime(_first(meta.get("runtime")))
    if duration is None and all(t.duration is not None for t in tracks):
        duration = int(round(sum(t.duration for t in tracks)))
    return BookPlan(title=_first(meta.get("title")) or identifier, author=_first(meta.get("creator")),
                    language=lang_code(_first(meta.get("language"))), duration=duration, cover=cover, tracks=tracks)
