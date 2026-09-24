from __future__ import annotations

from dataclasses import replace

import pytest

from bookmallow.store import search as sx
from bookmallow.store.models import BookPlan, SearchResult, StoreError, Track


def R(source, sid, **kw):
    return SearchResult(source, sid, kw.pop("title", f"{source}-{sid}"), **kw)


def const(results):
    def fn(*args, **kwargs):
        return list(results)
    return fn


def boom(*args, **kwargs):
    raise StoreError("provider_error", "down")


@pytest.fixture
def tconfig(config):
    return replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q", store_timeout_s=2.0)


def test_merge_dedupes_archive_against_librivox_and_sorts_prowlarr(tconfig):
    libri = [R("librivox", "1", alt_ids=["ia_one"]), R("librivox", "2")]
    arch = [R("archive", "ia_one"), R("archive", "ia_two")]
    prow = [R("prowlarr", "a", seeders=3), R("prowlarr", "b", seeders=None), R("prowlarr", "c", seeders=9)]
    cache = sx.SearchCache()
    results, providers = sx.unified_search("q", "all", tconfig, cache, librivox_search=const(libri),
                                           archive_search=const(arch), prowlarr_search=const(prow))
    assert [r.key for r in results] == ["librivox:1", "librivox:2", "archive:ia_two", "prowlarr:c", "prowlarr:a", "prowlarr:b"]
    assert providers == {"librivox": "ok", "archive": "ok", "prowlarr": "ok"}
    assert cache.lookup("prowlarr:c").seeders == 9 and cache.lookup("nope:x") is None


def test_provider_failure_is_isolated_and_disabled_reported(config):
    c = replace(config, store_archive=False)
    results, providers = sx.unified_search("q", "fr", c, sx.SearchCache(), librivox_search=const([R("librivox", "1")]),
                                           archive_search=boom, prowlarr_search=boom)
    assert [r.key for r in results] == ["librivox:1"]
    assert providers == {"librivox": "ok", "archive": "disabled", "prowlarr": "disabled"}
    results, providers = sx.unified_search("q2", "fr", config, sx.SearchCache(), librivox_search=boom,
                                           archive_search=const([R("archive", "z")]), prowlarr_search=boom)
    assert [r.key for r in results] == ["archive:z"] and providers["librivox"] == "error"


def test_cache_hit_skips_providers_and_expires(tconfig):
    now = [1000.0]
    cache = sx.SearchCache(ttl=600, clock=lambda: now[0])
    calls = []

    def counting(*a, **k):
        calls.append(1)
        return [R("librivox", "1")]

    sx.unified_search("q", "all", tconfig, cache, librivox_search=counting, archive_search=const([]), prowlarr_search=const([]))
    sx.unified_search("q", "all", tconfig, cache, librivox_search=counting, archive_search=const([]), prowlarr_search=const([]))
    assert len(calls) == 1
    now[0] += 601
    sx.unified_search("q", "all", tconfig, cache, librivox_search=counting, archive_search=const([]), prowlarr_search=const([]))
    assert len(calls) == 2
    assert cache.get("q", "fr") is None  # different language = different entry


def test_cache_evicts_oldest(config):
    cache = sx.SearchCache(max_entries=2)
    for i in range(3):
        cache.put(f"q{i}", "all", [R("librivox", str(i))], {})
    assert cache.get("q0", "all") is None and cache.get("q2", "all") is not None


def test_results_capped(config):
    many = [R("archive", str(i)) for i in range(80)]
    results, _ = sx.unified_search("q", "all", config, sx.SearchCache(), librivox_search=const([]), archive_search=const(many),
                                   prowlarr_search=const([]))
    assert len(results) == sx.MAX_RESULTS


def test_prowlarr_gate_reports_busy(tconfig, monkeypatch):
    monkeypatch.setattr(sx, "PROWLARR_GATE_TIMEOUT", 0.01)
    sx._PROWLARR_GATE.acquire()
    try:
        _, providers = sx.unified_search("q", "all", tconfig, sx.SearchCache(), librivox_search=const([]),
                                         archive_search=const([]), prowlarr_search=const([R("prowlarr", "x")]))
    finally:
        sx._PROWLARR_GATE.release()
    assert providers["prowlarr"] == "busy"


def test_resolve_result(config):
    plan = BookPlan("Titre", "Auteur", "fr", 100, "https://c/x.jpg", [Track("u", 1.0, "c")])
    r = sx.resolve_result("librivox", "904", config, librivox_plan=lambda sid, timeout: plan, archive_plan=boom)
    assert r.key == "librivox:904" and r.title == "Titre" and r.author == "Auteur" and r.duration == 100 and r.cover == "https://c/x.jpg"
    assert sx.resolve_result("prowlarr", "x", config) is None
    assert sx.resolve_result("archive", "x", replace(config, store_archive=False), archive_plan=boom) is None
    with pytest.raises(StoreError):
        sx.resolve_result("archive", "x", config, archive_plan=boom)
