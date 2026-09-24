"""LibriVox catalogue: public-domain audiobooks read by volunteers (spec §6.1, §6.3)."""
from __future__ import annotations

import re
from typing import Callable

from ..http import get_json
from ..models import BookPlan, SearchResult, StoreError, Track, lang_code

API = "https://librivox.org/api/feed/audiobooks"
LANG_NAMES = {"fr": "French", "en": "English"}
_IA = re.compile(r"archive\.org/details/([^/?#]+)")
Fetch = Callable[..., object]


def iarchive_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _IA.search(url)
    return m.group(1) if m else None


def _author(book: dict) -> str | None:
    names = []
    for a in book.get("authors") or []:
        full = " ".join(p for p in (str(a.get("first_name") or "").strip(), str(a.get("last_name") or "").strip()) if p)
        if full:
            names.append(full)
    return ", ".join(names[:2]) or None


def _int(value) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _result(book: dict) -> SearchResult:
    ia = iarchive_id(book.get("url_iarchive"))
    return SearchResult(
        source="librivox",
        source_id=str(book.get("id")),
        title=str(book.get("title") or "Sans titre"),
        author=_author(book),
        language=lang_code(book.get("language")),
        duration=_int(book.get("totaltimesecs")),
        cover=book.get("coverart_jpg") or book.get("coverart_thumbnail"),
        url=book.get("url_librivox"),
        alt_ids=[ia] if ia else [],
    )


def _books(payload) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("books"), list):
        return [b for b in payload["books"] if isinstance(b, dict)]
    return []  # {"error": "Audiobooks could not be found"} or anything unexpected


def search(q: str, lang: str, fetch: Fetch = get_json, timeout: float = 20.0, limit: int = 25) -> list[SearchResult]:
    common = {"format": "json", "extended": "1", "coverart": "1", "limit": str(limit)}
    seen: dict[str, SearchResult] = {}
    for params in ({"title": f"^{q}"}, {"author": q}):
        for book in _books(fetch(API, {**params, **common}, timeout=timeout)):
            result = _result(book)
            if lang != "all" and result.language != lang:
                continue
            seen.setdefault(result.source_id, result)
    return list(seen.values())[:limit]


def plan(book_id: str, fetch: Fetch = get_json, timeout: float = 20.0) -> BookPlan:
    books = _books(fetch(API, {"id": str(book_id), "format": "json", "extended": "1", "coverart": "1"}, timeout=timeout))
    if not books:
        raise StoreError("not_found", f"LibriVox book {book_id} not found")
    book = books[0]
    sections = [s for s in (book.get("sections") or []) if isinstance(s, dict) and s.get("listen_url")]
    sections.sort(key=lambda s: _int(s.get("section_number")) or 0)
    if not sections:
        raise StoreError("no_tracks", "LibriVox returned no sections for this book")
    result = _result(book)
    tracks = [Track(location=str(s["listen_url"]), duration=_float(s.get("playtime")), title=str(s.get("title") or ""))
              for s in sections]
    return BookPlan(title=result.title, author=result.author, language=result.language,
                    duration=result.duration, cover=result.cover, tracks=tracks)
