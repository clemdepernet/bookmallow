from __future__ import annotations

import pytest

from bookmallow.store.models import StoreError
from bookmallow.store.providers import archive as ia

DOC = {"identifier": "shortstories_2103_librivox", "title": "Short Stories", "creator": ["Guy de Maupassant", "Various"],
       "language": "eng", "runtime": "39:33:23"}
META = {
    "metadata": {"identifier": "shortstories_2103_librivox", "title": "Short Stories", "creator": "Guy de Maupassant",
                 "language": "eng", "runtime": "1:00:00"},
    "files": [
        {"name": "ss_002_maupassant.mp3", "length": "700.0", "track": "2", "source": "derivative"},
        {"name": "ss_002_maupassant_64kb.mp3", "length": "700.5", "track": "2", "source": "derivative"},
        {"name": "ss_002_maupassant_128kb.mp3", "length": "700.0", "track": "2", "source": "original"},
        {"name": "ss_001_maupassant_128kb.mp3", "length": "13:09", "track": "1", "source": "original"},
        {"name": "ss_001_maupassant.mp3", "length": "789.5", "track": "1", "source": "derivative"},
        {"name": "shortstories_2103.jpg", "source": "original"},
        {"name": "__ia_thumb.jpg", "source": "derivative"},
        {"name": "readme.txt"},
    ],
}


def fetcher(payload):
    calls = []

    def fetch(url, params=None, timeout=20.0, headers=None):
        calls.append((url, dict(params or {})))
        return payload

    fetch.calls = calls
    return fetch


def test_search_builds_query_and_maps_fields():
    fetch = fetcher({"response": {"numFound": 1, "docs": [DOC, {"identifier": "noname"}]}})
    results = ia.search("maupassant (short)", "en", fetch=fetch, limit=7)
    url, params = fetch.calls[0]
    assert url == ia.SEARCH and params["rows"] == "7" and params["output"] == "json"
    assert "collection:librivoxaudio" in params["q"] and "audio_bookspoetry" in params["q"]
    assert r"maupassant \(short\)" in params["q"] and "language:(eng OR english)" in params["q"]
    assert params["fl[]"] == ["identifier", "title", "creator", "language", "runtime"]
    assert len(results) == 2
    r = results[0]
    assert r.source == "archive" and r.source_id == "shortstories_2103_librivox" and r.title == "Short Stories"
    assert r.author == "Guy de Maupassant" and r.language == "en" and r.duration == 142403
    assert r.cover == "https://archive.org/services/img/shortstories_2103_librivox"
    assert r.url == "https://archive.org/details/shortstories_2103_librivox"
    assert results[1].title == "noname" and results[1].author is None


def test_search_lang_all_has_no_language_clause():
    fetch = fetcher({"response": {"docs": []}})
    assert ia.search("x", "all", fetch=fetch) == []
    assert "language:" not in fetch.calls[0][1]["q"]


def test_pick_tracks_prefers_64kb_then_original_and_sorts_by_track():
    picked = ia.pick_tracks(META["files"])
    assert [f["name"] for f in picked] == ["ss_001_maupassant_128kb.mp3", "ss_002_maupassant_64kb.mp3"]


def test_plan_builds_tracks_cover_and_duration():
    plan = ia.plan("shortstories_2103_librivox", fetch=fetcher(META))
    assert plan.title == "Short Stories" and plan.author == "Guy de Maupassant" and plan.language == "en"
    assert plan.duration == 3600
    assert plan.cover == "https://archive.org/download/shortstories_2103_librivox/shortstories_2103.jpg"
    assert [t.location for t in plan.tracks] == [
        "https://archive.org/download/shortstories_2103_librivox/ss_001_maupassant_128kb.mp3",
        "https://archive.org/download/shortstories_2103_librivox/ss_002_maupassant_64kb.mp3"]
    assert plan.tracks[0].duration == 789.0 and plan.tracks[1].duration == 700.5
    assert plan.tracks[0].title == "ss_001_maupassant_128kb"


def test_plan_falls_back_to_summed_lengths_and_service_image():
    meta = {"metadata": {"identifier": "x", "title": "X"}, "files": [{"name": "a b.mp3", "length": "10"}, {"name": "c.mp3", "length": "5"}]}
    plan = ia.plan("x", fetch=fetcher(meta))
    assert plan.duration == 15 and plan.cover == "https://archive.org/services/img/x"
    assert plan.tracks[0].location == "https://archive.org/download/x/a%20b.mp3"


def test_plan_errors():
    with pytest.raises(StoreError) as exc:
        ia.plan("nope", fetch=fetcher({"error": "Unable to fetch nope.json"}))
    assert exc.value.code == "not_found"
    with pytest.raises(StoreError) as exc:
        ia.plan("empty", fetch=fetcher({"metadata": {"identifier": "empty"}, "files": [{"name": "r.txt"}]}))
    assert exc.value.code == "no_tracks"


def test_escape_lucene():
    assert ia.escape_lucene('a:b "c" (d) e/f') == r'a\:b \"c\" \(d\) e\/f'
    assert ia.escape_lucene("rock && roll || jazz") == r"rock \&\& roll \|\| jazz"
