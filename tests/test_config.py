from __future__ import annotations

import pytest

from bookmallow import config as cfg


def test_defaults(tmp_path):
    c = cfg.load({"DATA_DIR": str(tmp_path)})
    assert c.data_dir == tmp_path
    assert c.max_files == 6
    assert c.default_quality == "64"
    assert c.app_password == ""
    assert c.auth_enabled is False
    assert c.min_free_mb == 500
    assert c.max_duration_hours == 0.0
    assert c.default_lang == "fr"
    assert c.force_https is False
    assert c.state_path == tmp_path / "state.json"


def test_reads_all_variables(tmp_path):
    c = cfg.load({
        "DATA_DIR": str(tmp_path), "MAX_FILES": "3", "DEFAULT_QUALITY": "128",
        "APP_PASSWORD": "pink", "SECRET_KEY": "abc", "MIN_FREE_MB": "50",
        "MAX_DURATION_HOURS": "2.5", "DEFAULT_LANG": "en", "FORCE_HTTPS": "1",
    })
    assert (c.max_files, c.default_quality, c.app_password, c.secret_key) == (3, "128", "pink", "abc")
    assert (c.min_free_mb, c.max_duration_hours, c.default_lang, c.force_https) == (50, 2.5, "en", True)
    assert c.auth_enabled is True


@pytest.mark.parametrize("env", [
    {"MAX_FILES": "0"}, {"MAX_FILES": "six"}, {"DEFAULT_QUALITY": "320"},
    {"DEFAULT_LANG": "de"}, {"MIN_FREE_MB": "-1"}, {"MAX_DURATION_HOURS": "-2"},
])
def test_invalid_values_raise(tmp_path, env):
    with pytest.raises(cfg.ConfigError):
        cfg.load({"DATA_DIR": str(tmp_path), **env})


def test_secret_is_generated_once_and_persisted(tmp_path):
    first = cfg.load({"DATA_DIR": str(tmp_path)}).secret_key
    second = cfg.load({"DATA_DIR": str(tmp_path)}).secret_key
    assert first == second
    assert len(first) == 64
    assert (tmp_path / ".secret").read_text().strip() == first


def test_qualities_table():
    assert cfg.QUALITIES["64"] == {"bitrate": "64k", "channels": 1, "kbps": 64}
    assert cfg.QUALITIES["128"]["channels"] == 2
    assert cfg.QUALITIES["192"]["bitrate"] == "192k"
