"""Minimal qBittorrent WebUI v2 client, stdlib only (spec §6.4)."""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .http import USER_AGENT
from .models import StoreError

LOGIN = "/api/v2/auth/login"
Transport = Callable[[str, str, dict | None, dict], tuple[int, str]]


class QbtError(StoreError):
    """qBittorrent refused or failed; `code` is qbt_auth, torrent_add or provider_error."""


@dataclass
class TorrentInfo:
    hash: str
    name: str
    progress: float
    state: str
    content_path: str
    size: int
    downloaded: int

    @classmethod
    def from_dict(cls, d: dict) -> "TorrentInfo":
        return cls(hash=str(d.get("hash", "")), name=str(d.get("name", "")), progress=float(d.get("progress") or 0.0),
                   state=str(d.get("state", "")), content_path=str(d.get("content_path", "")),
                   size=int(d.get("size") or 0), downloaded=int(d.get("downloaded") or 0))


class QbtClient:
    def __init__(self, base_url: str, user: str, password: str, transport: Transport | None = None, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self._user, self._password = user, password
        self._timeout = timeout
        self._transport = transport or self._urllib_transport
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    # ---- transport -------------------------------------------------------------------------

    def _urllib_transport(self, method: str, url: str, data: dict | None, headers: dict) -> tuple[int, str]:
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace") if exc.fp else ""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise QbtError("provider_error", f"qBittorrent unreachable: {getattr(exc, 'reason', exc)}") from exc

    def _call(self, path: str, data: dict | None = None, ok_statuses: tuple[int, ...] = (200, 204)) -> str:
        headers = {"User-Agent": USER_AGENT, "Referer": self.base_url, "Origin": self.base_url}
        method, url = "POST" if data is not None else "GET", f"{self.base_url}{path}"
        status, body = self._transport(method, url, data, headers)
        if status in (401, 403) and path != LOGIN:
            # The session cookie dies when qBittorrent restarts during a long download: log in again, retry once.
            self.login()
            status, body = self._transport(method, url, data, headers)
        if status in (401, 403):
            raise QbtError("qbt_auth", f"qBittorrent refused the credentials or session ({status})")
        if status not in ok_statuses:
            raise QbtError("provider_error", f"qBittorrent HTTP {status} on {path}: {body[:120]}")
        return body

    # ---- API ---------------------------------------------------------------------------------

    def login(self) -> None:
        body = self._call(LOGIN, {"username": self._user, "password": self._password})
        if body.strip() not in ("", "Ok."):  # 5.x answers 204 with an empty body, 4.x answers 200 "Ok."
            raise QbtError("qbt_auth", "qBittorrent login refused")

    def ensure_category(self, name: str) -> None:
        self._call("/api/v2/torrents/createCategory", {"category": name, "savePath": ""}, ok_statuses=(200, 204, 409))

    def add(self, download: str, category: str, tags: list[str]) -> None:
        body = self._call("/api/v2/torrents/add", {"urls": download, "category": category, "tags": ",".join(tags)})
        if body.strip() not in ("", "Ok."):
            raise QbtError("torrent_add", f"qBittorrent answered {body.strip()[:80] or 'nothing'}")

    def _infos(self, query: str) -> list[TorrentInfo]:
        body = self._call(f"/api/v2/torrents/info?{query}")
        try:
            items = json.loads(body or "[]")
        except ValueError as exc:
            raise QbtError("provider_error", "qBittorrent returned unreadable JSON") from exc
        if not isinstance(items, list):
            raise QbtError("provider_error", "qBittorrent returned an unexpected torrent list")
        return [TorrentInfo.from_dict(i) for i in items if isinstance(i, dict)]

    def find_by_tag(self, tag: str) -> TorrentInfo | None:
        infos = self._infos(f"tag={urllib.parse.quote(tag)}")
        return infos[0] if infos else None

    def info(self, torrent_hash: str) -> TorrentInfo | None:
        infos = self._infos(f"hashes={urllib.parse.quote(torrent_hash)}")
        return infos[0] if infos else None

    def delete(self, torrent_hash: str, delete_files: bool = True) -> None:
        self._call("/api/v2/torrents/delete", {"hashes": torrent_hash, "deleteFiles": "true" if delete_files else "false"})
