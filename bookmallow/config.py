"""Runtime configuration read from environment variables (spec §9)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
