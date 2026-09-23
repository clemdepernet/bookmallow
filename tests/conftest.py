from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is in sys.path for imports
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from bookmallow.config import Config


@pytest.fixture
def config(tmp_path) -> Config:
    """A Config pointing at a temporary data directory, auth disabled."""
    return Config(
        data_dir=tmp_path,
        max_files=6,
        default_quality="64",
        app_password="",
        secret_key="test-secret",
        min_free_mb=0,
        max_duration_hours=0.0,
        default_lang="fr",
        force_https=False,
    )
