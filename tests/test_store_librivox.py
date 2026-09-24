from __future__ import annotations

import pytest

from bookmallow.store.models import StoreError
from bookmallow.store.providers import librivox as lv

BOOK = {
    "id": "904", "title": "Boule de suif", "language": "French", "totaltimesecs": "15251",
    "authors": [{"first_name": "Guy de", "last_name": "Maupassant"}],
    "url_librivox": "https://librivox.org/boule-de-suif-by-guy-de-maupassant/",
    "url_iarchive": "https://www.archive.org/details/bouledesuif_0904_librivox",
    "coverart_jpg": "https://www.archive.org/download/LibrivoxCdCoverArt4/Ball_of_Fat_1005.jpg",
    "coverart_thumbnail": "https://www.archive.org/download/LibrivoxCdCoverArt4/Ball_of_Fat_1005_thumb.jpg",
    "sections": [
        {"section_number": "2", "title": "Partie 2", "listen_url": "https://archive.org/download/bouledesuif_0904_librivox/boule_02.mp3", "playtime": "1400"},
        {"section_number": "1", "title": "Partie 1", "listen_url": "https://archive.org/download/bouledesuif_0904_librivox/boule_01.mp3", "playtime": "1300.5"},
    ],
}
BOOK_EN = {**BOOK, "id": "1", "title": "Ball of Fat", "language": "English", "sections": []}


def fetcher(mapping):
    """mapping: param name → payload; the fetcher picks by whichever of title/author/id is present."""
    calls = []

    def fetch(url, params=None, timeout=20.0, headers=None):
        calls.append(dict(params or {}))
        for key in ("id", "title", "author"):
            if key in (params or {}):
                return mapping.get(key, {"error": "Audiobooks could not be found"})
        return {"error": "Audiobooks could not be found"}

    fetch.calls = calls
    return fetch


def test_search_merges_title_and_author_and_filters_language():
    fetch = fetcher({"title": {"books": [BOOK, BOOK_EN]}, "author": {"books": [BOOK]}})
    results = lv.search("boule", "fr", fetch=fetch)
    assert [r.source_id for r in results] == ["904"]
    r = results[0]
    assert r.source == "librivox" and r.title == "Boule de suif" and r.author == "Guy de Maupassant"
    assert r.language == "fr" and r.duration == 15251 and r.cover == BOOK["coverart_jpg"]
    assert r.url == BOOK["url_librivox"] and r.alt_ids == ["bouledesuif_0904_librivox"]
    assert fetch.calls[0]["title"] == "^boule" and fetch.calls[1]["author"] == "boule"
    assert fetch.calls[0]["extended"] == "1" and fetch.calls[0]["coverart"] == "1" and fetch.calls[0]["format"] == "json"


def test_search_all_languages_and_no_results():
    fetch = fetcher({"title": {"books": [BOOK, BOOK_EN]}})
    assert [r.language for r in lv.search("boule", "all", fetch=fetch)] == ["fr", "en"]
    assert lv.search("zzz", "all", fetch=fetcher({})) == []


def test_search_propagates_store_error():
    def boom(url, params=None, timeout=20.0, headers=None):
        raise StoreError("provider_error", "down")
    with pytest.raises(StoreError):
        lv.search("x", "all", fetch=boom)


def test_plan_orders_sections_and_reads_durations():
    fetch = fetcher({"id": {"books": [BOOK]}})
    plan = lv.plan("904", fetch=fetch)
    assert fetch.calls[0]["id"] == "904"
    assert plan.title == "Boule de suif" and plan.author == "Guy de Maupassant" and plan.language == "fr"
    assert plan.duration == 15251 and plan.cover == BOOK["coverart_jpg"]
    assert [t.title for t in plan.tracks] == ["Partie 1", "Partie 2"]
    assert plan.tracks[0].location.endswith("boule_01.mp3") and plan.tracks[0].duration == 1300.5


def test_plan_errors():
    with pytest.raises(StoreError) as exc:
        lv.plan("999", fetch=fetcher({}))
    assert exc.value.code == "not_found"
    with pytest.raises(StoreError) as exc:
        lv.plan("1", fetch=fetcher({"id": {"books": [BOOK_EN]}}))
    assert exc.value.code == "no_tracks"


def test_iarchive_id():
    assert lv.iarchive_id("https://www.archive.org/details/bouledesuif_0904_librivox") == "bouledesuif_0904_librivox"
    assert lv.iarchive_id("https://archive.org/details/x_y/") == "x_y"
    assert lv.iarchive_id(None) is None and lv.iarchive_id("https://example.com/") is None
