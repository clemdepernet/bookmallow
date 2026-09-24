"""Unified search across providers with a short-lived cache (spec §6.1, §6.2)."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable

from ..config import Config
from .models import SearchResult, StoreError
from .providers import archive, librivox, prowlarr

log = logging.getLogger(__name__)
MAX_RESULTS = 60
PROWLARR_GATE_TIMEOUT = 10.0
_PROWLARR_GATE = threading.Semaphore(1)


class SearchCache:
    """(query, lang) → (results, provider statuses), kept `ttl` seconds, at most `max_entries` entries."""

    def __init__(self, ttl: float = 600.0, max_entries: int = 200, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._max, self._clock = ttl, max_entries, clock
        self._entries: "OrderedDict[tuple[str, str], tuple[float, list[SearchResult], dict[str, str]]]" = OrderedDict()
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, (ts, _, _) in self._entries.items() if now - ts > self._ttl]:
            del self._entries[key]
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def get(self, q: str, lang: str) -> tuple[list[SearchResult], dict[str, str]] | None:
        with self._lock:
            self._purge()
            hit = self._entries.get((q, lang))
            return (list(hit[1]), dict(hit[2])) if hit else None

    def put(self, q: str, lang: str, results: list[SearchResult], providers: dict[str, str]) -> None:
        with self._lock:
            self._entries[(q, lang)] = (self._clock(), list(results), dict(providers))
            self._entries.move_to_end((q, lang))
            self._purge()

    def lookup(self, key: str) -> SearchResult | None:
        with self._lock:
            self._purge()
            for _, results, _ in reversed(self._entries.values()):
                for r in results:
                    if r.key == key:
                        return r
        return None


def _gated_prowlarr(fn, q: str, config: Config) -> list[SearchResult]:
    if not _PROWLARR_GATE.acquire(timeout=PROWLARR_GATE_TIMEOUT):
        raise StoreError("busy", "another Prowlarr search is still running")
    try:
        return fn(q, config)
    finally:
        _PROWLARR_GATE.release()


def unified_search(q: str, lang: str, config: Config, cache: SearchCache, *,
                   librivox_search=librivox.search, archive_search=archive.search,
                   prowlarr_search=prowlarr.search) -> tuple[list[SearchResult], dict[str, str]]:
    cached = cache.get(q, lang)
    if cached is not None:
        return cached
    providers = {"librivox": "disabled", "archive": "disabled", "prowlarr": "disabled"}
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="store-search")
    futures = {}
    if config.store_librivox:
        futures["librivox"] = pool.submit(librivox_search, q, lang, timeout=config.store_timeout_s)
    if config.store_archive:
        futures["archive"] = pool.submit(archive_search, q, lang, timeout=config.store_timeout_s)
    if config.torrent_enabled:
        futures["prowlarr"] = pool.submit(_gated_prowlarr, prowlarr_search, q, config)
    done, _pending = wait(futures.values(), timeout=config.store_timeout_s + PROWLARR_GATE_TIMEOUT + 5)
    pool.shutdown(wait=False, cancel_futures=True)

    found: dict[str, list[SearchResult]] = {}
    for name, fut in futures.items():
        if fut not in done:
            providers[name] = "error"
            log.warning("store search: %s timed out", name)
            continue
        try:
            found[name] = list(fut.result())
            providers[name] = "ok"
        except StoreError as exc:
            providers[name] = "busy" if exc.code == "busy" else "error"
            log.warning("store search: %s failed [%s]: %s", name, exc.code, exc.detail)
        except Exception:  # noqa: BLE001 - one broken provider must not break the others
            providers[name] = "error"
            log.exception("store search: %s crashed", name)

    libri = found.get("librivox", [])
    seen_ia = {alt for r in libri for alt in r.alt_ids}
    arch = [r for r in found.get("archive", []) if r.source_id not in seen_ia]
    prow = sorted(found.get("prowlarr", []), key=lambda r: (r.seeders if r.seeders is not None else -1), reverse=True)
    merged = (libri + arch + prow)[:MAX_RESULTS]
    cache.put(q, lang, merged, providers)
    return merged, providers


def resolve_result(source: str, source_id: str, config: Config, *,
                   librivox_plan=librivox.plan, archive_plan=archive.plan) -> SearchResult | None:
    """Rebuild a SearchResult for a free-source book that fell out of the cache (spec §6.2)."""
    if source == "librivox" and config.store_enabled and config.store_librivox:
        plan = librivox_plan(source_id, timeout=config.store_timeout_s)
    elif source == "archive" and config.store_enabled and config.store_archive:
        plan = archive_plan(source_id, timeout=config.store_timeout_s)
    else:
        return None
    return SearchResult(source=source, source_id=source_id, title=plan.title, author=plan.author,
                        language=plan.language, duration=plan.duration, cover=plan.cover)
