"""Tiny HTTP helpers for the store: JSON GET and small binary GET, stdlib only."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .. import __version__
from .models import StoreError

USER_AGENT = f"Bookmallow/{__version__} (+https://github.com/clemdepernet/bookmallow)"


def build_url(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}?{urllib.parse.urlencode(params, doseq=True)}"


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


def _open(url: str, timeout: float, headers: Mapping[str, str] | None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*", **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise StoreError("provider_error", f"{_host(url)}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise StoreError("provider_error", f"{_host(url)}: {reason}") from exc


def get_json(url: str, params: Mapping[str, Any] | None = None, timeout: float = 20.0,
             headers: Mapping[str, str] | None = None) -> Any:
    full = build_url(url, params)
    with _open(full, timeout, headers) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise StoreError("provider_error", f"{_host(url)}: unreadable JSON") from exc


def get_bytes(url: str, timeout: float = 10.0, max_bytes: int = 5_000_000) -> tuple[bytes, str]:
    """Download a small file (cover art). Returns (content, content-type)."""
    with _open(url, timeout, None) as resp:
        body = resp.read(max_bytes + 1)
        ctype = str(resp.headers.get("Content-Type", "")).split(";")[0].strip()
    if len(body) > max_bytes:
        raise StoreError("provider_error", f"{_host(url)}: file larger than {max_bytes} bytes")
    return body, ctype
