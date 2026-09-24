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


def test_store_defaults(tmp_path):
    c = cfg.load({"DATA_DIR": str(tmp_path)})
    assert c.store_enabled and c.store_librivox and c.store_archive
    assert c.prowlarr_url == "" and c.qbt_url == "" and c.torrent_enabled is False
    assert c.torrent_config_state == "disabled"
    assert c.qbt_category == "bookmallow" and c.path_map == ("/downloads", "/incoming")
    assert c.torrent_stall_hours == 12.0 and c.book_bitrate == "64k" and c.store_timeout_s == 20.0
    assert c.work_dir == tmp_path / ".work"


def test_store_torrent_enabled_and_partial(tmp_path):
    full = {"DATA_DIR": str(tmp_path), "PROWLARR_URL": "http://prowlarr:9696/", "PROWLARR_API_KEY": "k",
            "QBT_URL": "http://qbittorrent:8080", "QBT_USER": "admin", "QBT_PASSWORD": "pw",
            "QBT_PATH_MAP": "/dl/:/in/", "TORRENT_STALL_HOURS": "2", "BOOK_BITRATE": "96k", "STORE_TIMEOUT_S": "5"}
    c = cfg.load(full)
    assert c.torrent_enabled is True and c.torrent_config_state == "enabled"
    assert c.prowlarr_url == "http://prowlarr:9696" and c.qbt_url == "http://qbittorrent:8080"
    assert c.path_map == ("/dl", "/in") and c.torrent_stall_hours == 2.0 and c.book_bitrate == "96k"
    partial = cfg.load({"DATA_DIR": str(tmp_path), "PROWLARR_URL": "http://p:9696"})
    assert partial.torrent_enabled is False and partial.torrent_config_state == "partial"


@pytest.mark.parametrize("env", [{"BOOK_BITRATE": "64"}, {"BOOK_BITRATE": "abc"}, {"TORRENT_STALL_HOURS": "0"},
                                 {"STORE_TIMEOUT_S": "0.5"}, {"STORE_ENABLED": "maybe"}])
def test_store_invalid_values_raise(tmp_path, env):
    with pytest.raises(cfg.ConfigError):
        cfg.load({"DATA_DIR": str(tmp_path), **env})


def test_store_flags_off(tmp_path):
    c = cfg.load({"DATA_DIR": str(tmp_path), "STORE_ENABLED": "0", "STORE_ARCHIVE": "false"})
    assert c.store_enabled is False and c.store_archive is False and c.store_librivox is True
