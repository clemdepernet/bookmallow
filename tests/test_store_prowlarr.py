from __future__ import annotations

from dataclasses import replace

import pytest

from bookmallow.store.models import StoreError
from bookmallow.store.providers import prowlarr as pw

ITEMS = [
    {"guid": "https://idx/1", "title": "Le Comte de Monte-Cristo [FR] MP3 64k", "size": 900_000_000, "seeders": 12,
     "magnetUrl": "magnet:?xt=urn:btih:AAA", "downloadUrl": "https://idx/dl/1", "infoUrl": "https://idx/t/1", "indexer": "Idx"},
    {"guid": "https://idx/2", "title": "Pride and Prejudice (English) Audiobook", "size": 400_000_000, "seeders": 40,
     "downloadUrl": "https://idx/dl/2", "infoUrl": "https://idx/t/2", "indexer": "Idx"},
    {"guid": "https://idx/3", "title": "No download here", "size": 1, "seeders": 99},
]


@pytest.fixture
def tconfig(config):
    return replace(config, prowlarr_url="http://prowlarr:9696", prowlarr_api_key="KEY", qbt_url="http://qbt:8080", store_timeout_s=7.0)


def test_search_maps_sorts_and_hides_download_from_public(tconfig):
    calls = []

    def fetch(url, params=None, timeout=20.0, headers=None):
        calls.append((url, dict(params), timeout, dict(headers)))
        return ITEMS

    results = pw.search("monte", tconfig, fetch=fetch, limit=30)
    url, params, timeout, headers = calls[0]
    assert url == "http://prowlarr:9696/api/v1/search"
    assert params == {"query": "monte", "categories": "3030", "type": "search", "limit": "30"}
    assert timeout == 7.0 and headers == {"X-Api-Key": "KEY"}
    assert [r.seeders for r in results] == [40, 12]  # item 3 dropped (no download link)
    fr = results[1]
    assert fr.source == "prowlarr" and len(fr.source_id) == 16 and fr.download == "magnet:?xt=urn:btih:AAA"
    assert fr.size_bytes == 900_000_000 and fr.language == "fr" and fr.url == "https://idx/t/1" and fr.author == "Idx"
    assert results[0].download == "https://idx/dl/2" and results[0].language == "en"
    assert "download" not in fr.public()


def test_search_requires_configuration(config):
    with pytest.raises(StoreError) as exc:
        pw.search("x", config, fetch=lambda *a, **k: [])
    assert exc.value.code == "store_disabled"


def test_search_unexpected_payload(tconfig):
    assert pw.search("x", tconfig, fetch=lambda *a, **k: {"error": "nope"}) == []


@pytest.mark.parametrize("title,lang", [
    ("Livre audio FR - Dumas", "fr"), ("Roman [French] mp3", "fr"), ("Book (VF)", "fr"), ("Novel [English]", "en"),
    ("Something EN audiobook", "en"), ("Ambiguous title", None), ("Frank Herbert Dune", None),
])
def test_guess_language(title, lang):
    assert pw.guess_language(title) == lang
