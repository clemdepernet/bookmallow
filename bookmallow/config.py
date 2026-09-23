"""Runtime configuration read from environment variables (spec §9)."""
from __future__ import annotations

import os
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

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password)

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"


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
    )
