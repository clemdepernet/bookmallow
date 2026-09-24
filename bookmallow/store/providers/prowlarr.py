"""Prowlarr: Clem's indexer aggregator, audiobook category 3030 (spec §6.1, §6.4). Optional."""
from __future__ import annotations

import hashlib
import re
from typing import Callable

from ...config import Config
from ..http import get_json
from ..models import SearchResult, StoreError

CATEGORY_AUDIOBOOK = "3030"
_FR = re.compile(r"(?<![a-z])(fr|french|français|francais|vf|vff|multi\W*fr)(?![a-z])", re.I)
_EN = re.compile(r"(?<![a-z])(en|eng|english|vo|vostfr)(?![a-z])", re.I)
Fetch = Callable[..., object]


def guess_language(title: str) -> str | None:
    fr, en = bool(_FR.search(title)), bool(_EN.search(title))
    if fr and not en:
        return "fr"
    if en and not fr:
        return "en"
    return None


def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def search(q: str, config: Config, fetch: Fetch = get_json, limit: int = 30) -> list[SearchResult]:
    if not config.torrent_enabled:
        raise StoreError("store_disabled", "Prowlarr is not configured")
    payload = fetch(f"{config.prowlarr_url}/api/v1/search",
                    {"query": q, "categories": CATEGORY_AUDIOBOOK, "type": "search", "limit": str(limit)},
                    timeout=config.store_timeout_s, headers={"X-Api-Key": config.prowlarr_api_key})
    if not isinstance(payload, list):
        return []
    results: list[SearchResult] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        download = item.get("magnetUrl") or item.get("downloadUrl")
        guid = str(item.get("guid") or download or "")
        if not download or not guid:
            continue
        title = str(item.get("title") or "Sans titre")
        results.append(SearchResult(
            source="prowlarr",
            source_id=hashlib.sha1(guid.encode("utf-8")).hexdigest()[:16],
            title=title,
            author=str(item.get("indexer")) if item.get("indexer") else None,
            language=guess_language(title),
            size_bytes=_int(item.get("size")),
            seeders=_int(item.get("seeders")),
            url=item.get("infoUrl"),
            download=str(download),
        ))
    results.sort(key=lambda r: (r.seeders if r.seeders is not None else -1), reverse=True)
    return results[:limit]
