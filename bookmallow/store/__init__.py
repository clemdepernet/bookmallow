"""Audiobook store: search providers, acquisition pipelines and their shared helpers (spec v1.1)."""
from __future__ import annotations

from ..config import Config


def providers_available(config: Config) -> dict[str, str]:
    """Static availability from configuration: 'enabled', 'disabled' or 'partial' (torrent half-configured)."""
    if not config.store_enabled:
        return {"librivox": "disabled", "archive": "disabled", "prowlarr": "disabled"}
    return {
        "librivox": "enabled" if config.store_librivox else "disabled",
        "archive": "enabled" if config.store_archive else "disabled",
        "prowlarr": config.torrent_config_state,
    }
