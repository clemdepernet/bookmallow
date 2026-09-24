"""Internet Archive: complements LibriVox with other free audiobook collections (spec §6.1, §6.3)."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import quote

from ..http import get_json
from ..models import BookPlan, SearchResult, StoreError, Track, lang_code, parse_runtime

SEARCH = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
DOWNLOAD = "https://archive.org/download/"
IMG = "https://archive.org/services/img/"
COLLECTIONS = "(collection:librivoxaudio OR collection:audio_bookspoetry)"
LANG_QUERY = {"fr": "(fre OR fra OR french)", "en": "(eng OR english)"}
FIELDS = ["identifier", "title", "creator", "language", "runtime"]
_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/])')
_BITRATE = re.compile(r"_(\d{2,3}kb|vbr)$", re.I)
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


def pick_tracks(files: list[dict]) -> list[dict]:
    """One MP3 per chapter: prefer the `_64kb` derivative, then the original, then anything; ordered by track/name."""
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

    def order(f: dict):
        track = str(f.get("track") or "")
        num = int(track.split("/")[0]) if track.split("/")[0].isdigit() else 10**9
        return (num, _track_key(str(f["name"])))

    return sorted(chosen, key=order)


def plan(identifier: str, fetch: Fetch = get_json, timeout: float = 20.0) -> BookPlan:
    payload = fetch(f"{META}{identifier}", None, timeout=timeout)
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
        length = parse_runtime(f.get("length"))
        raw = f.get("length")
        duration = float(raw) if isinstance(raw, str) and re.fullmatch(r"\d+(\.\d+)?", raw) else (float(length) if length is not None else None)
        tracks.append(Track(location=f"{DOWNLOAD}{identifier}/{quote(name)}", duration=duration, title=name[:-4]))
    images = [str(f["name"]) for f in files
              if str(f.get("name", "")).lower().endswith((".jpg", ".jpeg", ".png")) and not str(f["name"]).startswith("__ia_thumb")]
    cover = f"{DOWNLOAD}{identifier}/{quote(images[0])}" if images else f"{IMG}{identifier}"
    duration = parse_runtime(_first(meta.get("runtime")))
    if duration is None and all(t.duration is not None for t in tracks):
        duration = int(round(sum(t.duration for t in tracks)))
    return BookPlan(title=_first(meta.get("title")) or identifier, author=_first(meta.get("creator")),
                    language=lang_code(_first(meta.get("language"))), duration=duration, cover=cover, tracks=tracks)
