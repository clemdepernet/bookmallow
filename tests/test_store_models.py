from __future__ import annotations

import pytest

from bookmallow.store import providers_available
from bookmallow.store.models import BookPlan, SearchResult, StoreError, Track, lang_code, parse_runtime


def test_search_result_key_and_public():
    r = SearchResult("prowlarr", "abc", "Titre", download="magnet:?xt=1", seeders=3)
    d = r.public()
    assert r.key == "prowlarr:abc" and d["key"] == "prowlarr:abc"
    assert "download" not in d and d["seeders"] == 3 and d["alt_ids"] == []


@pytest.mark.parametrize("value,code", [
    ("French", "fr"), ("fre", "fr"), ("fra", "fr"), ("fr", "fr"), ("English", "en"), ("eng", "en"),
    ("German", "de"), ("spa", "es"), ("Multilingual", "mul"), (None, None), ("", None), ("Klingon", None),
])
def test_lang_code(value, code):
    assert lang_code(value) == code


@pytest.mark.parametrize("text,seconds", [
    ("39:33:23", 142403), ("40:46", 2446), ("789.52", 790), ("12", 12), ("", None), (None, None), ("abc", None),
])
def test_parse_runtime(text, seconds):
    assert parse_runtime(text) == seconds


def test_store_error_and_plan_shape():
    exc = StoreError("no_tracks", "empty")
    assert exc.code == "no_tracks" and str(exc) == "empty"
    plan = BookPlan("T", None, "fr", 10, None, [Track("https://x/1.mp3", 5.0, "Un")])
    assert plan.tracks[0].title == "Un"


def test_providers_available(config):
    from dataclasses import replace
    assert providers_available(config) == {"librivox": "enabled", "archive": "enabled", "prowlarr": "disabled"}
    c = replace(config, store_librivox=False, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    assert providers_available(c) == {"librivox": "disabled", "archive": "enabled", "prowlarr": "enabled"}
    c = replace(config, store_enabled=False)
    assert providers_available(c) == {"librivox": "disabled", "archive": "disabled", "prowlarr": "disabled"}
