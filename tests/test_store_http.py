from __future__ import annotations

import io
import urllib.error

import pytest

from bookmallow.store import http
from bookmallow.store.models import StoreError


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str = "application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_build_url_encodes_and_repeats_lists():
    url = http.build_url("https://a/b", {"q": "bo ule", "fl[]": ["x", "y"], "n": 3})
    assert url == "https://a/b?q=bo+ule&fl%5B%5D=x&fl%5B%5D=y&n=3"
    assert http.build_url("https://a/b", None) == "https://a/b"


def test_get_json_success(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        return FakeResponse(b'{"ok": 1}')

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    assert http.get_json("https://a/b", {"q": "x"}, timeout=7) == {"ok": 1}
    assert seen == {"url": "https://a/b?q=x", "ua": http.USER_AGENT, "timeout": 7}


@pytest.mark.parametrize("boom", [
    urllib.error.HTTPError("https://a/b", 503, "down", {}, None),
    urllib.error.URLError("dns"),
    TimeoutError("slow"),
])
def test_get_json_errors_become_store_error(monkeypatch, boom):
    def fake_urlopen(req, timeout):
        raise boom

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(StoreError) as exc:
        http.get_json("https://a/b")
    assert exc.value.code == "provider_error" and "a" in exc.value.detail
    assert exc.value.status == (503 if isinstance(boom, urllib.error.HTTPError) else None)


def test_get_json_404_keeps_status(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError("https://librivox.org/api", 404, "Not Found", {}, None)

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(StoreError) as exc:
        http.get_json("https://librivox.org/api")
    assert exc.value.code == "provider_error" and exc.value.status == 404 and "HTTP 404" in exc.value.detail


def test_get_json_unreadable(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"<html>"))
    with pytest.raises(StoreError) as exc:
        http.get_json("https://a/b")
    assert exc.value.code == "provider_error"


def test_get_bytes_caps_size_and_returns_type(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"x" * 10, "image/jpeg"))
    body, ctype = http.get_bytes("https://a/c.jpg", max_bytes=100)
    assert body == b"x" * 10 and ctype == "image/jpeg"
    with pytest.raises(StoreError):
        http.get_bytes("https://a/c.jpg", max_bytes=5)


def test_read_failure_becomes_store_error(monkeypatch):
    class Flaky(FakeResponse):
        def read(self, *a):
            raise OSError("connection reset")
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout: Flaky(b""))
    with pytest.raises(StoreError) as exc:
        http.get_json("https://a/b")
    assert exc.value.code == "provider_error" and "transfer failed" in exc.value.detail
    with pytest.raises(StoreError):
        http.get_bytes("https://a/c.jpg")
