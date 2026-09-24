"""Runtime configuration read from environment variables (spec §9)."""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

QUALITIES: dict[str, dict] = {
    "64": {"bitrate": "64k", "channels": 1, "kbps": 64},
    "128": {"bitrate": "128k", "channels": 2, "kbps": 128},
    "192": {"bitrate": "192k", "channels": 2, "kbps": 192},
}
LANGS = ("fr", "en")
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}
_BITRATE = re.compile(r"^\d{2,3}k$")


class ConfigError(ValueError):
    """An environment variable holds an unusable value."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    max_files: int
    default_quality: str
    app_password: str
    secret_key: str
    min_free_mb: int
    max_duration_hours: float
    default_lang: str
    force_https: bool
    store_enabled: bool = True
    store_librivox: bool = True
    store_archive: bool = True
    prowlarr_url: str = ""
    prowlarr_api_key: str = ""
    qbt_url: str = ""
    qbt_user: str = ""
    qbt_password: str = ""
    qbt_category: str = "bookmallow"
    qbt_path_map: str = "/downloads:/incoming"
    torrent_stall_hours: float = 12.0
    book_bitrate: str = "64k"
    store_timeout_s: float = 20.0

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password)

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def torrent_enabled(self) -> bool:
        return bool(self.prowlarr_url and self.prowlarr_api_key and self.qbt_url)

    @property
    def torrent_config_state(self) -> str:
        """'enabled', 'partial' (some torrent variables set, not all) or 'disabled'."""
        if self.torrent_enabled:
            return "enabled"
        return "partial" if (self.prowlarr_url or self.prowlarr_api_key or self.qbt_url) else "disabled"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / ".work"

    @property
    def path_map(self) -> tuple[str, str]:
        """(path as seen by qBittorrent, same path as seen by Bookmallow), without trailing slashes."""
        remote, _, local = self.qbt_path_map.partition(":")
        return (remote.rstrip("/") or "/"), (local.rstrip("/") or "/")


def _int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def _float(env: Mapping[str, str], name: str, default: float, minimum: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def _choice(env: Mapping[str, str], name: str, default: str, choices: Iterable[str]) -> str:
    choices = tuple(choices)
    raw = env.get(name, "").strip() or default
    if raw not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)}, got {raw!r}")
    return raw


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    raise ConfigError(f"{name} must be a boolean (1/0, true/false), got {raw!r}")


def _bitrate(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name, "").strip().lower() or default
    if not _BITRATE.match(raw):
        raise ConfigError(f"{name} must look like 64k, got {raw!r}")
    return raw


def _path_map(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name, "").strip() or default
    remote, sep, local = raw.partition(":")
    if not sep or not remote.strip() or not local.strip():
        raise ConfigError(f"{name} must look like /downloads:/incoming (qBittorrent path:Bookmallow path), got {raw!r}")
    return raw


def _url(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip().rstrip("/")


def ensure_secret(data_dir: Path) -> str:
    """Return a stable secret key, generating and persisting one on first run."""
    path = data_dir / ".secret"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_hex(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def load(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config from `env` (defaults to os.environ), creating DATA_DIR if needed."""
    env = os.environ if env is None else env
    data_dir = Path(env.get("DATA_DIR", "").strip() or "/data").expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = env.get("SECRET_KEY", "").strip() or ensure_secret(data_dir)
    return Config(
        data_dir=data_dir,
        max_files=_int(env, "MAX_FILES", 6, 1),
        default_quality=_choice(env, "DEFAULT_QUALITY", "64", QUALITIES),
        app_password=env.get("APP_PASSWORD", ""),
        secret_key=secret,
        min_free_mb=_int(env, "MIN_FREE_MB", 500, 0),
        max_duration_hours=_float(env, "MAX_DURATION_HOURS", 0.0, 0.0),
        default_lang=_choice(env, "DEFAULT_LANG", "fr", LANGS),
        force_https=env.get("FORCE_HTTPS", "").strip().lower() in _TRUTHY,
        store_enabled=_bool(env, "STORE_ENABLED", True),
        store_librivox=_bool(env, "STORE_LIBRIVOX", True),
        store_archive=_bool(env, "STORE_ARCHIVE", True),
        prowlarr_url=_url(env, "PROWLARR_URL"),
        prowlarr_api_key=env.get("PROWLARR_API_KEY", "").strip(),
        qbt_url=_url(env, "QBT_URL"),
        qbt_user=env.get("QBT_USER", ""),
        qbt_password=env.get("QBT_PASSWORD", ""),
        qbt_category=env.get("QBT_CATEGORY", "").strip() or "bookmallow",
        qbt_path_map=_path_map(env, "QBT_PATH_MAP", "/downloads:/incoming"),
        torrent_stall_hours=_float(env, "TORRENT_STALL_HOURS", 12.0, 0.1),
        book_bitrate=_bitrate(env, "BOOK_BITRATE", "64k"),
        store_timeout_s=_float(env, "STORE_TIMEOUT_S", 20.0, 1.0),
    )
