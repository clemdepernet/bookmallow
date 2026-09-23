from __future__ import annotations

import pytest

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
