# Bookmallow v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer Bookmallow v1 : un conteneur Docker auto-hébergeable qui convertit des vidéos YouTube (même de 17 h) en MP3 audiobook via une interface web pastel, avec file d'attente, conversion en streaming, rétention des 6 derniers fichiers et mot de passe optionnel.

**Architecture:** Un package Python `bookmallow/` découpé en petits modules (config, urls, names, jobs, state, retention, metadata, converter, jobqueue, auth, app). Flask sert une page unique et une API JSON ; un unique thread worker exécute la file ; la conversion est un tube `yt-dlp -o - | ffmpeg` qui n'écrit que le MP3 final (sous `.part.mp3` puis renommé). L'état est persisté dans `state.json` à côté des MP3.

**Tech Stack:** Python 3.12, Flask 3, gunicorn (1 worker, 8 threads), yt-dlp (+ deno comme runtime JS), ffmpeg (libmp3lame), pytest, Docker multi-arch (arm64/amd64) via GitHub Actions vers ghcr.io. Frontend HTML/CSS/JS vanilla sans CDN.

**Spec:** `docs/superpowers/specs/2026-09-23-bookmallow-design.md`

## Global Constraints

- Dépôt : `/home/clem/bookmallow`, remote `upstream` = dépôt d'origine (MIT, historique conservé). Le remote `origin` (`clemdepernet/bookmallow`) est créé en Task 14 seulement.
- Prose des commits, README et docs : le README est bilingue FR puis EN ; code, commentaires, messages d'erreur serveur et commits en anglais ; l'interface est traduite FR/EN côté client.
- Python : `from __future__ import annotations` en tête de chaque module ; aucune dépendance hors `flask`, `gunicorn`, `yt-dlp[default]` (runtime) et `pytest` (dev).
- Aucune ressource externe (CDN, police web) dans le frontend.
- Variables d'environnement et défauts exacts (spec §9) : `DATA_DIR=/data`, `MAX_FILES=6`, `DEFAULT_QUALITY=64`, `APP_PASSWORD=` (vide), `SECRET_KEY` (généré dans `/data/.secret`), `MIN_FREE_MB=500`, `MAX_DURATION_HOURS=0` (0 = illimité), `DEFAULT_LANG=fr`, `TZ=UTC`, `PUID=1000`, `PGID=1000`, `FORCE_HTTPS` (absent = non).
- Qualités : `64` = 64 kbps mono, `128` = 128 kbps stéréo, `192` = 192 kbps stéréo.
- Palette (spec §10) : crème `#FFF7F9`, rose poudré `#F8C8D8`, rose vif `#E75A8C`, lilas `#C9B6F2`, menthe `#BDEBD5`, corail `#F49A8B`, prune `#4A2A3C`.
- Port conteneur `5000`, port hôte d'exemple `7843`. Volume unique `/data`.
- Tests : `pytest -q` depuis la racine du dépôt, dans le venv `.venv` (Python 3.13 sur le Pi, 3.12 dans l'image ; le code doit tourner sur les deux).
- Les tests ne lancent jamais le vrai `yt-dlp` ni le vrai `ffmpeg` ; les processus sont injectés (`runner`, `popen`, `conversion_factory`).

---

## File Structure

```
bookmallow/
  __init__.py          version string
  config.py            Config dataclass + load(env) + ensure_secret()
  urls.py              parse(raw) -> ParsedUrl ; InvalidUrl ; watch_url()
  names.py             safe_filename(), unique_name()
  jobs.py              Status, Job dataclass, new_job(), now_iso()
  state.py             StateStore(path).load()/save()/trim()
  retention.py         list_mp3(), prune(), next_to_go(), remove_partials(), PART_SUFFIX
  metadata.py          VideoMeta/PlaylistMeta, fetch_video(), fetch_playlist(), classify_error(), MetadataError
  converter.py         ConvertRequest, Conversion(run/cancel), ytdlp_command(), ffmpeg_command(), parse_progress_line()
  jobqueue.py          JobQueue(submit/cancel/get/snapshot/process_next/start), DuplicateJob, estimate_bytes()
  auth.py              login_required, check_password(), is_authenticated()
  app.py               create_app(config, jobqueue, start_worker, fetch_playlist), build_state()
  templates/index.html, templates/login.html
  static/style.css, static/app.js, static/logo.svg
tests/
  conftest.py, test_config.py, test_urls.py, test_names.py, test_jobs_state.py, test_retention.py,
  test_metadata.py, test_converter.py, test_jobqueue.py, test_app.py
wsgi.py, requirements.txt, requirements-dev.txt, pyproject.toml, .gitignore, .dockerignore
Dockerfile, entrypoint.sh, docker-compose.yml
.github/workflows/ci.yml, .github/workflows/release.yml
README.md, LICENSE, CHANGELOG.md, CONTRIBUTING.md, docs/reddit-post.md, docs/screenshot.png
```

---

### Task 1 : Nettoyage du dépôt d'origine et squelette Python

**Files:**
- Delete: `app.py`, `templates/index.html`, `youtube-to-mp3.sh`, `youtube-downloader-screenshot.png`, `portainer-template.md`, `PORTAINER.md`, `docker-compose-no-build.yml`
- Create: `bookmallow/__init__.py`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `tests/conftest.py`, `tests/test_smoke.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `bookmallow.__version__ = "1.0.0"` ; venv `.venv` avec pytest.

- [ ] **Step 1 : Supprimer les fichiers de l'ancien projet**

```bash
cd /home/clem/bookmallow
git rm -q app.py templates/index.html youtube-to-mp3.sh youtube-downloader-screenshot.png portainer-template.md PORTAINER.md docker-compose-no-build.yml
```

- [ ] **Step 2 : Écrire le squelette**

`bookmallow/__init__.py` :
```python
"""Bookmallow: turn YouTube videos into audiobook MP3s, gently."""

__version__ = "1.0.0"
```

`pyproject.toml` :
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`requirements.txt` :
```
flask>=3.0,<4
gunicorn>=22,<24
yt-dlp[default]>=2026.1.1
```

`requirements-dev.txt` :
```
-r requirements.txt
pytest>=8,<9
```

`.gitignore` (remplacer le contenu) :
```
__pycache__/
*.pyc
.venv/
.pytest_cache/
data/
*.part.mp3
.env
```

`bookmallow/config.py` (version minimale, complétée en Task 2 ; ne pas ajouter `load` ici) :
```python
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
```

`tests/conftest.py` :
```python
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
```

`tests/test_smoke.py` :
```python
from bookmallow import __version__


def test_version_is_semver():
    assert __version__.count(".") == 2
```

- [ ] **Step 3 : Créer le venv et lancer le test**

```bash
cd /home/clem/bookmallow && python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt && .venv/bin/pytest tests/test_smoke.py
```
Attendu : `1 passed`. Si l'installation de `yt-dlp[default]` est lente sur le Pi, c'est normal (≈ 1 min).

- [ ] **Step 4 : Commit**

```bash
git add -A && git commit -m "chore: strip original app, add Python skeleton and test tooling"
```

---

### Task 2 : `config.py`

**Files:**
- Create: `bookmallow/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `QUALITIES: dict[str, dict]` (clés `"64"`, `"128"`, `"192"`, valeurs `{"bitrate": "64k", "channels": 1, "kbps": 64}`…), `LANGS = ("fr", "en")`, `class ConfigError(ValueError)`, `@dataclass(frozen=True) class Config` (champs : `data_dir: Path, max_files: int, default_quality: str, app_password: str, secret_key: str, min_free_mb: int, max_duration_hours: float, default_lang: str, force_https: bool` ; propriétés `auth_enabled -> bool`, `state_path -> Path`), `ensure_secret(data_dir: Path) -> str`, `load(env: Mapping[str, str] | None = None) -> Config`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_config.py` :
```python
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
```

- [ ] **Step 2 : Vérifier que les tests échouent**

Run : `.venv/bin/pytest tests/test_config.py`
Attendu : FAIL (`load` inexistant ou `ConfigError` manquant).

- [ ] **Step 3 : Implémenter**

`bookmallow/config.py` :
```python
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
```

- [ ] **Step 4 : Vérifier que les tests passent**

Run : `.venv/bin/pytest tests/test_config.py`
Attendu : `10 passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/config.py tests/test_config.py && git commit -m "feat: environment-driven configuration"
```

---

### Task 3 : `urls.py`

**Files:**
- Create: `bookmallow/urls.py`
- Test: `tests/test_urls.py`

**Interfaces:**
- Produces: `class InvalidUrl(ValueError)`, `@dataclass(frozen=True) class ParsedUrl(video_id: str | None, playlist_id: str | None)` avec propriétés `is_playlist -> bool`, `watch_url -> str`, `playlist_url -> str` ; `parse(raw: str) -> ParsedUrl` ; `watch_url(video_id: str) -> str`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_urls.py` :
```python
from __future__ import annotations

import pytest

from bookmallow import urls


@pytest.mark.parametrize("raw", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "http://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "youtube.com/watch?v=dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
])
def test_video_urls(raw):
    p = urls.parse(raw)
    assert p.video_id == "dQw4w9WgXcQ"
    assert p.is_playlist is False
    assert p.watch_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_playlist_only():
    p = urls.parse("https://www.youtube.com/playlist?list=PLabc123DEF")
    assert p.video_id is None
    assert p.playlist_id == "PLabc123DEF"
    assert p.is_playlist is True
    assert p.playlist_url == "https://www.youtube.com/playlist?list=PLabc123DEF"
    with pytest.raises(urls.InvalidUrl):
        _ = p.watch_url


def test_video_inside_playlist():
    p = urls.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc123DEF&index=3")
    assert p.video_id == "dQw4w9WgXcQ"
    assert p.playlist_id == "PLabc123DEF"
    assert p.is_playlist is True


@pytest.mark.parametrize("raw", [
    "", "   ", "https://vimeo.com/12345", "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/", "https://www.youtube.com/watch?v=short",
    "https://evil.com/?u=youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
    "javascript:alert(1)",
])
def test_rejects_non_youtube_or_idless(raw):
    with pytest.raises(urls.InvalidUrl):
        urls.parse(raw)


def test_watch_url_helper():
    assert urls.watch_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `.venv/bin/pytest tests/test_urls.py`
Attendu : FAIL (`ModuleNotFoundError: bookmallow.urls`).

- [ ] **Step 3 : Implémenter**

`bookmallow/urls.py` :
```python
"""Parse and validate YouTube links. Anything else is refused (spec §2, §6.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

ALLOWED_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
})
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,}$")
_PATH_ID = re.compile(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})(?:[/?]|$)")


class InvalidUrl(ValueError):
    """The text is not a usable YouTube video or playlist link."""


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class ParsedUrl:
    video_id: str | None
    playlist_id: str | None

    @property
    def is_playlist(self) -> bool:
        return self.playlist_id is not None

    @property
    def watch_url(self) -> str:
        if self.video_id is None:
            raise InvalidUrl("no video id")
        return watch_url(self.video_id)

    @property
    def playlist_url(self) -> str:
        if self.playlist_id is None:
            raise InvalidUrl("no playlist id")
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"


def parse(raw: str) -> ParsedUrl:
    text = (raw or "").strip()
    if not text:
        raise InvalidUrl("empty")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise InvalidUrl("not_youtube")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidUrl("not_youtube")

    query = parse_qs(parts.query)
    video_id: str | None = None
    playlist_id: str | None = None

    if host.endswith("youtu.be"):
        candidate = parts.path.strip("/").split("/")[0]
        if _VIDEO_ID.match(candidate):
            video_id = candidate
    else:
        v = query.get("v", [""])[0]
        if _VIDEO_ID.match(v):
            video_id = v
        else:
            m = _PATH_ID.match(parts.path)
            if m:
                video_id = m.group(1)

    lst = query.get("list", [""])[0]
    if lst and _PLAYLIST_ID.match(lst):
        playlist_id = lst

    if video_id is None and playlist_id is None:
        raise InvalidUrl("no_id")
    return ParsedUrl(video_id=video_id, playlist_id=playlist_id)
```

- [ ] **Step 4 : Vérifier que les tests passent**

Run : `.venv/bin/pytest tests/test_urls.py`
Attendu : tous `passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/urls.py tests/test_urls.py && git commit -m "feat: YouTube URL parsing and validation"
```

---

### Task 4 : `names.py`

**Files:**
- Create: `bookmallow/names.py`
- Test: `tests/test_names.py`

**Interfaces:**
- Produces: `safe_filename(title: str | None, video_id: str, ext: str = ".mp3", max_len: int = 120) -> str` (forme `"<titre> [<video_id>].mp3"`), `unique_name(name: str, existing: Iterable[str]) -> str`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_names.py` :
```python
from __future__ import annotations

from bookmallow.names import safe_filename, unique_name

VID = "dQw4w9WgXcQ"


def test_basic_shape():
    assert safe_filename("Mon livre audio", VID) == f"Mon livre audio [{VID}].mp3"


def test_strips_forbidden_and_control_chars():
    name = safe_filename('A:B/C\\D*E?F"G<H>I|J\x07K', VID)
    assert name == f"ABCDEFGHIJK [{VID}].mp3"


def test_collapses_whitespace_and_trims_dots():
    assert safe_filename("  Titre   avec    espaces ... ", VID) == f"Titre avec espaces [{VID}].mp3"


def test_empty_title_falls_back():
    assert safe_filename("", VID) == f"audiobook [{VID}].mp3"
    assert safe_filename(None, VID) == f"audiobook [{VID}].mp3"
    assert safe_filename("???", VID) == f"audiobook [{VID}].mp3"


def test_truncates_to_max_len():
    name = safe_filename("x" * 500, VID, max_len=60)
    assert len(name) <= 60
    assert name.endswith(f" [{VID}].mp3")


def test_keeps_accents():
    assert safe_filename("Éloge de l'été — épisode 1", VID).startswith("Éloge de l'été — épisode 1")


def test_unique_name():
    existing = {"a.mp3", "a (2).mp3"}
    assert unique_name("b.mp3", existing) == "b.mp3"
    assert unique_name("a.mp3", existing) == "a (3).mp3"
    assert unique_name("noext", {"noext"}) == "noext (2)"
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `.venv/bin/pytest tests/test_names.py` → FAIL (module absent).

- [ ] **Step 3 : Implémenter**

`bookmallow/names.py` :
```python
"""Turn video titles into safe, unique file names."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")
FALLBACK = "audiobook"


def safe_filename(title: str | None, video_id: str, ext: str = ".mp3", max_len: int = 120) -> str:
    """`<title> [<video_id>]<ext>`, stripped of characters that upset any OS."""
    base = unicodedata.normalize("NFC", title or "")
    base = _FORBIDDEN.sub("", base)
    base = _SPACES.sub(" ", base).strip(" .")
    suffix = f" [{video_id}]{ext}"
    room = max(max_len - len(suffix), 1)
    if len(base) > room:
        base = base[:room].rstrip(" .")
    if not base:
        base = FALLBACK
    return f"{base}{suffix}"


def unique_name(name: str, existing: Iterable[str]) -> str:
    """Append ` (2)`, ` (3)`… before the extension until the name is free."""
    taken = set(existing)
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem} ({n}){dot}{ext}"
        if candidate not in taken:
            return candidate
        n += 1
```

- [ ] **Step 4 : Vérifier que les tests passent**

Run : `.venv/bin/pytest tests/test_names.py` → `7 passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/names.py tests/test_names.py && git commit -m "feat: safe and unique file names"
```

---

### Task 5 : `jobs.py` et `state.py`

**Files:**
- Create: `bookmallow/jobs.py`, `bookmallow/state.py`
- Test: `tests/test_jobs_state.py`

**Interfaces:**
- Produces (`jobs.py`) : `class Status(str, Enum)` avec `QUEUED, FETCHING, CONVERTING, DONE, FAILED, CANCELLED` ; `ACTIVE_STATUSES` ; `now_iso() -> str` ; `@dataclass class Job` (champs : `id, url, video_id, quality, title=None, duration=None, thumbnail=None, channel=None, status=Status.QUEUED, progress=0.0, error=None, error_code=None, filename=None, size_bytes=None, created_at=now_iso(), started_at=None, finished_at=None`), méthodes `is_active` (property), `to_dict() -> dict`, `Job.from_dict(d) -> Job` ; `new_job(url: str, video_id: str, quality: str) -> Job`.
- Produces (`state.py`) : `class StateStore(path: Path, max_jobs: int = 50)` avec `load() -> list[Job]`, `save(jobs: Iterable[Job]) -> list[Job]` (renvoie la liste conservée après trim), `trim(jobs: list[Job]) -> list[Job]`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_jobs_state.py` :
```python
from __future__ import annotations

import json

from bookmallow.jobs import ACTIVE_STATUSES, Job, Status, new_job, now_iso
from bookmallow.state import StateStore


def test_new_job_defaults():
    j = new_job("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ", "64")
    assert len(j.id) == 8
    assert j.status is Status.QUEUED
    assert j.is_active is True
    assert j.progress == 0.0
    assert j.created_at.endswith("+00:00")


def test_active_statuses():
    assert ACTIVE_STATUSES == {Status.QUEUED, Status.FETCHING, Status.CONVERTING}
    j = new_job("u", "v", "64")
    j.status = Status.DONE
    assert j.is_active is False


def test_roundtrip_dict():
    j = new_job("u", "v", "128")
    j.status = Status.FAILED
    j.error_code = "private"
    d = j.to_dict()
    assert d["status"] == "failed"
    assert Job.from_dict(d) == j


def test_from_dict_ignores_unknown_and_defaults_status():
    j = Job.from_dict({"id": "abcd1234", "url": "u", "video_id": "v", "quality": "64", "future_field": 1})
    assert j.status is Status.QUEUED


def test_now_iso_has_no_microseconds():
    assert "." not in now_iso()


def test_store_load_missing(tmp_path):
    assert StateStore(tmp_path / "state.json").load() == []


def test_store_save_and_load(tmp_path):
    store = StateStore(tmp_path / "state.json")
    jobs = [new_job("u1", "v1", "64"), new_job("u2", "v2", "192")]
    store.save(jobs)
    assert store.load() == jobs
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["version"] == 1
    assert not (tmp_path / "state.json.tmp").exists()


def test_store_corrupt_file_is_moved_aside(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert StateStore(path).load() == []
    assert not path.exists()
    assert (tmp_path / "state.json.bad").read_text() == "{not json"


def test_store_trims_finished_jobs_but_keeps_active(tmp_path):
    store = StateStore(tmp_path / "state.json", max_jobs=3)
    jobs = []
    for i in range(5):
        j = new_job(f"u{i}", f"v{i}", "64")
        j.created_at = f"2026-01-0{i + 1}T00:00:00+00:00"
        j.status = Status.DONE if i < 4 else Status.QUEUED
        jobs.append(j)
    kept = store.save(jobs)
    assert [j.video_id for j in kept] == ["v2", "v3", "v4"]
    assert [j.video_id for j in store.load()] == ["v2", "v3", "v4"]
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `.venv/bin/pytest tests/test_jobs_state.py` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/jobs.py` :
```python
"""Job model shared by the queue, the store and the API (spec §5)."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum


class Status(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    CONVERTING = "converting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = frozenset({Status.QUEUED, Status.FETCHING, Status.CONVERTING})


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Job:
    id: str
    url: str
    video_id: str
    quality: str
    title: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    channel: str | None = None
    status: Status = Status.QUEUED
    progress: float = 0.0
    error: str | None = None
    error_code: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["status"] = Status(kwargs.get("status") or "queued")
        return cls(**kwargs)


def new_job(url: str, video_id: str, quality: str) -> Job:
    return Job(id=uuid.uuid4().hex[:8], url=url, video_id=video_id, quality=quality)
```

`bookmallow/state.py` :
```python
"""Persist the job list to state.json atomically (spec §5, §6.8)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

from .jobs import Job

log = logging.getLogger(__name__)
VERSION = 1


class StateStore:
    def __init__(self, path: Path, max_jobs: int = 50):
        self.path = Path(path)
        self.max_jobs = max_jobs

    def load(self) -> list[Job]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [Job.from_dict(item) for item in data["jobs"]]
        except (ValueError, TypeError, KeyError) as exc:
            bad = self.path.with_name(self.path.name + ".bad")
            log.warning("state file unreadable (%s); moving it to %s", exc, bad)
            os.replace(self.path, bad)
            return []

    def trim(self, jobs: list[Job]) -> list[Job]:
        """Drop the oldest finished jobs so at most max_jobs remain; active jobs are never dropped."""
        excess = len(jobs) - self.max_jobs
        if excess <= 0:
            return list(jobs)
        drop: set[str] = set()
        for job in sorted((j for j in jobs if not j.is_active), key=lambda j: j.created_at):
            if excess <= 0:
                break
            drop.add(job.id)
            excess -= 1
        return [j for j in jobs if j.id not in drop]

    def save(self, jobs: Iterable[Job]) -> list[Job]:
        kept = self.trim(list(jobs))
        payload = {"version": VERSION, "jobs": [j.to_dict() for j in kept]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        return kept
```

- [ ] **Step 4 : Vérifier que les tests passent**

Run : `.venv/bin/pytest tests/test_jobs_state.py` → `9 passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/jobs.py bookmallow/state.py tests/test_jobs_state.py && git commit -m "feat: job model and atomic state store"
```

---

### Task 6 : `retention.py`

**Files:**
- Create: `bookmallow/retention.py`
- Test: `tests/test_retention.py`

**Interfaces:**
- Produces: `PART_SUFFIX = ".part.mp3"`, `list_mp3(directory: Path) -> list[Path]` (plus récent en premier, ignore les `.part.mp3`), `prune(directory: Path, max_files: int) -> list[Path]` (supprimés), `next_to_go(directory: Path, max_files: int) -> str | None`, `remove_partials(directory: Path) -> list[Path]`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_retention.py` :
```python
from __future__ import annotations

import os

from bookmallow import retention


def make(tmp_path, name, age):
    """Create `name` whose mtime is `age` seconds in the past."""
    p = tmp_path / name
    p.write_bytes(b"x")
    t = 1_800_000_000 - age
    os.utime(p, (t, t))
    return p


def test_list_mp3_newest_first_ignoring_partials(tmp_path):
    make(tmp_path, "old.mp3", 300)
    make(tmp_path, "new.mp3", 10)
    make(tmp_path, "mid.mp3", 100)
    make(tmp_path, "wip.part.mp3", 0)
    make(tmp_path, "notes.txt", 0)
    assert [p.name for p in retention.list_mp3(tmp_path)] == ["new.mp3", "mid.mp3", "old.mp3"]


def test_prune_keeps_newest_n(tmp_path):
    for i in range(5):
        make(tmp_path, f"f{i}.mp3", i * 10)  # f0 newest, f4 oldest
    deleted = retention.prune(tmp_path, 3)
    assert sorted(p.name for p in deleted) == ["f3.mp3", "f4.mp3"]
    assert sorted(p.name for p in tmp_path.glob("*.mp3")) == ["f0.mp3", "f1.mp3", "f2.mp3"]


def test_prune_nothing_when_under_limit(tmp_path):
    make(tmp_path, "a.mp3", 0)
    assert retention.prune(tmp_path, 6) == []


def test_next_to_go(tmp_path):
    assert retention.next_to_go(tmp_path, 2) is None
    make(tmp_path, "a.mp3", 100)
    assert retention.next_to_go(tmp_path, 2) is None
    make(tmp_path, "b.mp3", 10)
    assert retention.next_to_go(tmp_path, 2) == "a.mp3"


def test_remove_partials(tmp_path):
    make(tmp_path, "keep.mp3", 0)
    make(tmp_path, "x.part.mp3", 0)
    make(tmp_path, "y.part.mp3", 0)
    removed = retention.remove_partials(tmp_path)
    assert sorted(p.name for p in removed) == ["x.part.mp3", "y.part.mp3"]
    assert [p.name for p in tmp_path.iterdir()] == ["keep.mp3"]
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_retention.py` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/retention.py` :
```python
"""Keep only the newest MAX_FILES MP3s (spec §6.5) and clean up partial files (spec §6.8)."""
from __future__ import annotations

from pathlib import Path

PART_SUFFIX = ".part.mp3"


def list_mp3(directory: Path) -> list[Path]:
    """Finished MP3 files, newest first. Partial files are not MP3s yet."""
    files = [
        p for p in Path(directory).glob("*.mp3")
        if p.is_file() and not p.name.endswith(PART_SUFFIX)
    ]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def prune(directory: Path, max_files: int) -> list[Path]:
    """Delete every MP3 beyond the newest `max_files`; return what was deleted."""
    deleted: list[Path] = []
    for path in list_mp3(directory)[max_files:]:
        try:
            path.unlink()
            deleted.append(path)
        except FileNotFoundError:
            pass
    return deleted


def next_to_go(directory: Path, max_files: int) -> str | None:
    """Name of the file the next conversion will evict, or None if there is still room."""
    files = list_mp3(directory)
    if len(files) < max_files:
        return None
    return files[-1].name


def remove_partials(directory: Path) -> list[Path]:
    removed: list[Path] = []
    for path in Path(directory).glob(f"*{PART_SUFFIX}"):
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_retention.py` → `5 passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/retention.py tests/test_retention.py && git commit -m "feat: retention of the newest N files"
```

---

### Task 7 : `metadata.py`

**Files:**
- Create: `bookmallow/metadata.py`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Produces: `Runner = Callable[[list[str], float], str]` (args yt-dlp sans le binaire, timeout → stdout ; lève `MetadataError`), `class MetadataError(Exception)` avec attributs `code: str`, `detail: str` ; `@dataclass class VideoMeta(video_id, title, duration: int | None, thumbnail: str | None, channel: str | None, chapters: list[dict])` où chaque chapitre est `{"title": str, "start": float, "end": float}` ; `@dataclass class PlaylistEntry(video_id, title, duration)` ; `@dataclass class PlaylistMeta(playlist_id, title, entries: list[PlaylistEntry])` ; `classify_error(stderr: str) -> tuple[str, str]` (code, dernière ligne) ; `default_runner(args, timeout) -> str` ; `fetch_video(url, runner=default_runner, timeout=60.0) -> VideoMeta` ; `fetch_playlist(url, runner=default_runner, timeout=90.0) -> PlaylistMeta`.
- Codes d'erreur possibles : `private`, `age`, `geo`, `unavailable`, `live`, `timeout`, `metadata`, `ytdlp`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_metadata.py` :
```python
from __future__ import annotations

import json

import pytest

from bookmallow import metadata as md

VIDEO_JSON = {
    "id": "dQw4w9WgXcQ", "title": "Un livre", "duration": 36000.0, "thumbnail": "https://i.ytimg.com/x.jpg",
    "channel": "La Chaîne", "uploader": "uploader-name",
    "chapters": [{"title": "Ch 1", "start_time": 0, "end_time": 600.5}, {"title": "Ch 2", "start_time": 600.5, "end_time": 36000}],
}


def runner_returning(payload):
    calls = []

    def runner(args, timeout):
        calls.append((args, timeout))
        return json.dumps(payload)

    runner.calls = calls
    return runner


def test_fetch_video_maps_fields():
    runner = runner_returning(VIDEO_JSON)
    meta = md.fetch_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ", runner=runner)
    assert meta.video_id == "dQw4w9WgXcQ"
    assert meta.title == "Un livre"
    assert meta.duration == 36000
    assert meta.thumbnail == "https://i.ytimg.com/x.jpg"
    assert meta.channel == "La Chaîne"
    assert meta.chapters == [{"title": "Ch 1", "start": 0.0, "end": 600.5}, {"title": "Ch 2", "start": 600.5, "end": 36000.0}]
    args, timeout = runner.calls[0]
    assert "--dump-single-json" in args and "--no-playlist" in args and args[-1].endswith("dQw4w9WgXcQ")
    assert timeout == 60.0


def test_fetch_video_falls_back_to_uploader_and_no_duration():
    payload = {**VIDEO_JSON, "channel": None, "duration": None, "chapters": None}
    meta = md.fetch_video("u", runner=runner_returning(payload))
    assert meta.channel == "uploader-name"
    assert meta.duration is None
    assert meta.chapters == []


def test_fetch_video_refuses_live():
    with pytest.raises(md.MetadataError) as exc:
        md.fetch_video("u", runner=runner_returning({**VIDEO_JSON, "is_live": True}))
    assert exc.value.code == "live"


def test_fetch_video_unreadable_json():
    with pytest.raises(md.MetadataError) as exc:
        md.fetch_video("u", runner=lambda a, t: "not json")
    assert exc.value.code == "metadata"


def test_fetch_playlist():
    payload = {"id": "PLxyz", "title": "Ma liste", "entries": [
        {"id": "aaaaaaaaaaa", "title": "Part 1", "duration": 100},
        None,
        {"id": "bbbbbbbbbbb", "title": None, "duration": None},
        {"title": "no id"},
    ]}
    runner = runner_returning(payload)
    pl = md.fetch_playlist("https://www.youtube.com/playlist?list=PLxyz", runner=runner)
    assert pl.playlist_id == "PLxyz" and pl.title == "Ma liste"
    assert [(e.video_id, e.title, e.duration) for e in pl.entries] == [
        ("aaaaaaaaaaa", "Part 1", 100), ("bbbbbbbbbbb", "Sans titre", None)]
    assert "--flat-playlist" in runner.calls[0][0]


@pytest.mark.parametrize("stderr,code", [
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [youtube] abc: Sign in to confirm your age", "age"),
    ("ERROR: The uploader has not made this video available in your country", "geo"),
    ("ERROR: [youtube] abc: Video unavailable", "unavailable"),
    ("WARNING: something\nERROR: This live event will begin in 3 hours", "live"),
    ("ERROR: something new and weird", "ytdlp"),
])
def test_classify_error(stderr, code):
    got_code, detail = md.classify_error(stderr)
    assert got_code == code
    assert detail == stderr.splitlines()[-1].strip()


def test_default_runner_raises_when_binary_missing(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise FileNotFoundError("yt-dlp")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(md.MetadataError) as exc:
        md.default_runner(["--version"], 5)
    assert exc.value.code == "ytdlp"


def test_default_runner_maps_nonzero_exit(monkeypatch):
    import subprocess

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Private video"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(md.MetadataError) as exc:
        md.default_runner(["x"], 5)
    assert exc.value.code == "private"
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_metadata.py` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/metadata.py` :
```python
"""Fetch video / playlist metadata with `yt-dlp --dump-single-json` (spec §4, §11)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable

Runner = Callable[[list[str], float], str]

_COMMON = ["--no-warnings", "--no-progress", "--dump-single-json"]
_ERROR_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("private", ("private video",)),
    ("age", ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users")),
    ("geo", ("available in your country", "geo restricted", "geo-restricted", "blocked it in your country")),
    ("unavailable", ("video unavailable", "has been removed", "no longer available", "does not exist", "not available")),
    ("live", ("live event", "premieres in", "is a live stream", "live stream")),
]


class MetadataError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class VideoMeta:
    video_id: str
    title: str
    duration: int | None
    thumbnail: str | None
    channel: str | None
    chapters: list[dict] = field(default_factory=list)


@dataclass
class PlaylistEntry:
    video_id: str
    title: str
    duration: int | None


@dataclass
class PlaylistMeta:
    playlist_id: str
    title: str
    entries: list[PlaylistEntry]


def last_line(text: str, limit: int = 200) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else "")[:limit]


def classify_error(stderr: str) -> tuple[str, str]:
    """Map yt-dlp's stderr to a short error code plus its last line."""
    text = stderr.lower()
    for code, needles in _ERROR_PATTERNS:
        if any(needle in text for needle in needles):
            return code, last_line(stderr)
    return "ytdlp", last_line(stderr)


def default_runner(args: list[str], timeout: float) -> str:
    try:
        proc = subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise MetadataError("ytdlp", "yt-dlp is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MetadataError("timeout", f"yt-dlp took more than {int(timeout)} s") from exc
    if proc.returncode != 0:
        code, detail = classify_error(proc.stderr)
        raise MetadataError(code, detail or f"yt-dlp exited with {proc.returncode}")
    return proc.stdout


def _parse(out: str) -> dict:
    try:
        info = json.loads(out)
    except ValueError as exc:
        raise MetadataError("metadata", "yt-dlp returned unreadable metadata") from exc
    if not isinstance(info, dict):
        raise MetadataError("metadata", "yt-dlp returned unexpected metadata")
    return info


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def fetch_video(url: str, runner: Runner = default_runner, timeout: float = 60.0) -> VideoMeta:
    info = _parse(runner([*_COMMON, "--no-playlist", url], timeout))
    if info.get("is_live"):
        raise MetadataError("live", "live streams cannot be converted")
    chapters = [
        {"title": str(c.get("title") or ""), "start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0)}
        for c in (info.get("chapters") or []) if isinstance(c, dict)
    ]
    return VideoMeta(
        video_id=str(info.get("id") or ""),
        title=str(info.get("title") or "Sans titre"),
        duration=_int_or_none(info.get("duration")),
        thumbnail=info.get("thumbnail"),
        channel=info.get("channel") or info.get("uploader"),
        chapters=chapters,
    )


def fetch_playlist(url: str, runner: Runner = default_runner, timeout: float = 90.0) -> PlaylistMeta:
    info = _parse(runner([*_COMMON, "--flat-playlist", url], timeout))
    entries = [
        PlaylistEntry(video_id=str(e["id"]), title=str(e.get("title") or "Sans titre"), duration=_int_or_none(e.get("duration")))
        for e in (info.get("entries") or []) if isinstance(e, dict) and e.get("id")
    ]
    return PlaylistMeta(playlist_id=str(info.get("id") or ""), title=str(info.get("title") or "Playlist"), entries=entries)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_metadata.py` → tous `passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/metadata.py tests/test_metadata.py && git commit -m "feat: yt-dlp metadata fetching and error classification"
```

---

### Task 8 : `converter.py` (tube yt-dlp → ffmpeg)

**Files:**
- Create: `bookmallow/converter.py`
- Test: `tests/test_converter.py`

**Interfaces:**
- Consumes: `QUALITIES` (Task 2), `PART_SUFFIX` (Task 6), `classify_error` (Task 7).
- Produces: `YTDLP_FORMAT`, `class ConversionError(Exception)` (`code`, `detail`), `class Cancelled(Exception)`, `@dataclass class ConvertRequest(url, quality, out_path: Path, duration=None, title=None, channel=None, chapters=[])` avec propriété `part_path -> Path` ; `ytdlp_command(url) -> list[str]` ; `ffmpeg_command(req, meta_path: Path | None) -> list[str]` ; `write_ffmetadata(req) -> str` ; `parse_progress_line(line: str) -> int | None` (µs) ; `progress_percent(out_time_us: int, duration: int | None) -> float` ; `class Conversion(req, on_progress: Callable[[float], None] | None = None, popen=subprocess.Popen, kill_grace: float = 5.0)` avec `run() -> None` (bloquant) et `cancel() -> None` (thread-safe).

- [ ] **Step 1 : Écrire les tests**

`tests/test_converter.py` :
```python
from __future__ import annotations

import io
import subprocess
import threading
import time
from pathlib import Path

import pytest

from bookmallow import converter as cv


def req(tmp_path, **kw) -> cv.ConvertRequest:
    base = dict(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", quality="64", out_path=tmp_path / "Livre [dQw4w9WgXcQ].mp3", duration=100)
    base.update(kw)
    return cv.ConvertRequest(**base)


class FakeProc:
    def __init__(self, cmd, stdout_bytes=b"", stderr_bytes=b"", rc=0):
        self.cmd = cmd
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self.rc = rc
        self.pid = 999999

    def wait(self):
        return self.rc

    def poll(self):
        return self.rc


def fake_popen(*, ff_progress=b"", ff_rc=0, ff_stderr=b"", yt_rc=0, yt_stderr=b"", write_part=True):
    """Return (popen, calls). First call = yt-dlp, second = ffmpeg."""
    calls = []

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0] == "yt-dlp":
            return FakeProc(cmd, stderr_bytes=yt_stderr, rc=yt_rc)
        if write_part:
            Path(cmd[-1]).write_bytes(b"ID3fake")
        return FakeProc(cmd, stdout_bytes=ff_progress, stderr_bytes=ff_stderr, rc=ff_rc)

    return popen, calls


def test_ytdlp_command_streams_to_stdout():
    cmd = cv.ytdlp_command("URL")
    assert cmd[0] == "yt-dlp" and cmd[-1] == "URL"
    assert cmd[cmd.index("-o") + 1] == "-"
    assert "--no-playlist" in cmd
    assert cmd[cmd.index("-f") + 1] == cv.YTDLP_FORMAT


def test_ffmpeg_command_quality_64_is_mono(tmp_path):
    cmd = cv.ffmpeg_command(req(tmp_path, title="Livre", channel="Chaîne"), None)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "pipe:0"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-b:a") + 1] == "64k"
    assert cmd[cmd.index("-codec:a") + 1] == "libmp3lame"
    assert "-progress" in cmd and cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert cmd[-1] == str(tmp_path / "Livre [dQw4w9WgXcQ].part.mp3")
    assert "title=Livre" in cmd and "artist=Chaîne" in cmd


def test_ffmpeg_command_quality_192_is_stereo_and_uses_meta_file(tmp_path):
    cmd = cv.ffmpeg_command(req(tmp_path, quality="192"), tmp_path / "m.ffmeta")
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-b:a") + 1] == "192k"
    assert str(tmp_path / "m.ffmeta") in cmd
    assert "-map_chapters" in cmd and "-map_metadata" in cmd


def test_write_ffmetadata_escapes_and_lists_chapters(tmp_path):
    r = req(tmp_path, title="A=B;C", channel="X", chapters=[{"title": "Un", "start": 0, "end": 1.5}, {"title": "Vide", "start": 5, "end": 5}])
    text = cv.write_ffmetadata(r)
    assert text.startswith(";FFMETADATA1\n")
    assert "title=A\\=B\;C" in text
    assert text.count("[CHAPTER]") == 1
    assert "START=0\nEND=1500\ntitle=Un" in text


@pytest.mark.parametrize("line,expected", [
    ("out_time_us=1500000", 1_500_000), ("out_time_ms=1500000", 1_500_000), ("out_time_us=-1", 0),
    ("frame=12", None), ("out_time=00:00:01.5", None), ("out_time_us=abc", None), ("", None),
])
def test_parse_progress_line(line, expected):
    assert cv.parse_progress_line(line) == expected


def test_progress_percent():
    assert cv.progress_percent(50_000_000, 100) == 50.0
    assert cv.progress_percent(500_000_000, 100) == 99.9
    assert cv.progress_percent(10, None) == 0.0


def test_run_success_renames_part_and_reports_progress(tmp_path):
    popen, calls = fake_popen(ff_progress=b"frame=1\nout_time_us=25000000\nprogress=continue\nout_time_us=100000000\nprogress=end\n")
    seen = []
    r = req(tmp_path)
    cv.Conversion(r, on_progress=seen.append, popen=popen).run()
    assert r.out_path.exists() and not r.part_path.exists()
    assert seen == [25.0, 99.9]
    (yt_cmd, yt_kw), (ff_cmd, ff_kw) = calls
    assert yt_cmd[0] == "yt-dlp" and ff_cmd[0] == "ffmpeg"
    assert yt_kw["stdout"] is subprocess.PIPE and yt_kw["start_new_session"] is True
    assert ff_kw["start_new_session"] is True


def test_run_writes_metadata_file_when_chapters_and_cleans_it(tmp_path):
    popen, calls = fake_popen()
    r = req(tmp_path, chapters=[{"title": "Un", "start": 0, "end": 10}])
    cv.Conversion(r, popen=popen).run()
    ff_cmd = calls[1][0]
    assert any(arg.endswith(".ffmeta") for arg in ff_cmd)
    assert not list(tmp_path.glob("*.ffmeta"))


def test_run_ffmpeg_failure(tmp_path):
    popen, _ = fake_popen(ff_rc=1, ff_stderr=b"pipe:0: Invalid data found when processing input\n")
    r = req(tmp_path)
    with pytest.raises(cv.ConversionError) as exc:
        cv.Conversion(r, popen=popen).run()
    assert exc.value.code == "ffmpeg"
    assert "Invalid data" in exc.value.detail
    assert not r.part_path.exists() and not r.out_path.exists()


def test_run_ytdlp_error_wins_over_ffmpeg_noise(tmp_path):
    popen, _ = fake_popen(ff_rc=1, ff_stderr=b"pipe:0: Invalid data\n", yt_rc=1,
                          yt_stderr=b"ERROR: [youtube] dQw4w9WgXcQ: Private video\n")
    with pytest.raises(cv.ConversionError) as exc:
        cv.Conversion(req(tmp_path), popen=popen).run()
    assert exc.value.code == "private"


def test_run_broken_pipe_from_ytdlp_is_reported_as_ffmpeg(tmp_path):
    popen, _ = fake_popen(ff_rc=1, ff_stderr=b"Conversion failed!\n", yt_rc=1,
                          yt_stderr=b"ERROR: unable to write data: [Errno 32] Broken pipe\n")
    with pytest.raises(cv.ConversionError) as exc:
        cv.Conversion(req(tmp_path), popen=popen).run()
    assert exc.value.code == "ffmpeg"


def test_cancel_before_run_raises_cancelled(tmp_path):
    popen, _ = fake_popen()
    r = req(tmp_path)
    conv = cv.Conversion(r, popen=popen, kill_grace=0.01)
    conv.cancel()
    with pytest.raises(cv.Cancelled):
        conv.run()
    assert not r.part_path.exists()


def test_cancel_kills_real_processes(tmp_path):
    """Both fake tools are `sleep 30`; cancel() must end run() quickly via SIGTERM on the process groups."""
    def popen(cmd, **kw):
        return subprocess.Popen(["sleep", "30"], **kw)

    conv = cv.Conversion(req(tmp_path), popen=popen, kill_grace=1.0)
    result = {}

    def target():
        try:
            conv.run()
        except BaseException as exc:  # noqa: BLE001
            result["exc"] = exc

    t = threading.Thread(target=target)
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    conv.cancel()
    t.join(timeout=5)
    assert not t.is_alive()
    assert isinstance(result["exc"], cv.Cancelled)
    assert time.monotonic() - started < 4
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_converter.py` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/converter.py` :
```python
"""Stream a video's audio through ffmpeg into an MP3 without an intermediate file (spec §6.3)."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import QUALITIES
from .metadata import classify_error
from .retention import PART_SUFFIX

YTDLP_FORMAT = "bestaudio[ext=webm]/bestaudio[acodec^=opus]/bestaudio/best"
_ESCAPE = re.compile(r"([=;#\\\n])")


class ConversionError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class Cancelled(Exception):
    """The conversion was cancelled by the user."""


@dataclass
class ConvertRequest:
    url: str
    quality: str
    out_path: Path
    duration: int | None = None
    title: str | None = None
    channel: str | None = None
    chapters: list[dict] = field(default_factory=list)

    @property
    def part_path(self) -> Path:
        name = self.out_path.name
        stem = name[:-4] if name.endswith(".mp3") else name
        return self.out_path.with_name(stem + PART_SUFFIX)


def ytdlp_command(url: str) -> list[str]:
    return ["yt-dlp", "--no-playlist", "--no-warnings", "--no-progress", "--quiet",
            "-f", YTDLP_FORMAT, "-o", "-", url]


def _tags(req: ConvertRequest) -> dict[str, str]:
    tags = {"comment": req.url}
    if req.title:
        tags["title"] = req.title
    if req.channel:
        tags["artist"] = req.channel
        tags["album_artist"] = req.channel
    return tags


def ffmpeg_command(req: ConvertRequest, meta_path: Path | None) -> list[str]:
    q = QUALITIES[req.quality]
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0"]
    if meta_path is not None:
        cmd += ["-i", str(meta_path), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
    else:
        cmd += ["-map", "0:a"]
        for key, value in _tags(req).items():
            cmd += ["-metadata", f"{key}={value}"]
    cmd += ["-vn", "-ac", str(q["channels"]), "-codec:a", "libmp3lame", "-b:a", q["bitrate"],
            "-id3v2_version", "3", "-progress", "pipe:1", "-nostats", "-y", "-f", "mp3", str(req.part_path)]
    return cmd


def _escape(value: str) -> str:
    return _ESCAPE.sub(r"\\\1", value)


def write_ffmetadata(req: ConvertRequest) -> str:
    lines = [";FFMETADATA1"]
    for key, value in _tags(req).items():
        lines.append(f"{key}={_escape(value)}")
    for ch in req.chapters:
        start = int(round(float(ch.get("start", 0)) * 1000))
        end = int(round(float(ch.get("end", 0)) * 1000))
        if end <= start:
            continue
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_escape(str(ch.get('title') or ''))}"]
    return "\n".join(lines) + "\n"


def parse_progress_line(line: str) -> int | None:
    """Microseconds converted so far, from one `ffmpeg -progress` line; None for other keys."""
    key, sep, value = line.strip().partition("=")
    if not sep or key not in ("out_time_us", "out_time_ms"):
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        return None


def progress_percent(out_time_us: int, duration: int | None) -> float:
    if not duration:
        return 0.0
    return round(min(out_time_us / (duration * 1_000_000) * 100.0, 99.9), 1)


class _Tail(threading.Thread):
    """Drain a stderr pipe in the background, keeping the last few lines."""

    def __init__(self, stream, keep: int = 20):
        super().__init__(daemon=True)
        self._stream = stream
        self._lines: deque[str] = deque(maxlen=keep)
        self.start()

    def run(self) -> None:
        for raw in self._stream:
            self._lines.append(raw.decode("utf-8", "replace").rstrip())

    def text(self) -> str:
        return "\n".join(self._lines)


def _terminate(procs, grace: float) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = [p for p in procs if p.poll() is None]
        if not alive:
            return
        for proc in alive:
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.05)


def _unlink(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


class Conversion:
    """One yt-dlp → ffmpeg pipeline. `run()` blocks; `cancel()` may be called from any thread."""

    def __init__(self, req: ConvertRequest, on_progress: Callable[[float], None] | None = None,
                 popen=subprocess.Popen, kill_grace: float = 5.0):
        self.req = req
        self._on_progress = on_progress or (lambda percent: None)
        self._popen = popen
        self._kill_grace = kill_grace
        self._procs: list = []
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            procs = list(self._procs)
        _terminate(procs, self._kill_grace)

    def run(self) -> None:
        req = self.req
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path: Path | None = None
        try:
            if self._cancelled.is_set():
                raise Cancelled()
            if req.chapters:
                meta_path = req.part_path.with_suffix(".ffmeta")
                meta_path.write_text(write_ffmetadata(req), encoding="utf-8")

            yt = self._popen(ytdlp_command(req.url), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            ff = self._popen(ffmpeg_command(req, meta_path), stdin=yt.stdout, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
            yt.stdout.close()  # ffmpeg now owns the read end; yt-dlp gets EPIPE if ffmpeg dies
            with self._lock:
                self._procs = [yt, ff]
            if self._cancelled.is_set():
                _terminate([yt, ff], self._kill_grace)

            yt_err, ff_err = _Tail(yt.stderr), _Tail(ff.stderr)
            for raw in ff.stdout:
                us = parse_progress_line(raw.decode("utf-8", "replace"))
                if us is not None:
                    self._on_progress(progress_percent(us, req.duration))
            ff_rc, yt_rc = ff.wait(), yt.wait()
            yt_err.join(timeout=2)
            ff_err.join(timeout=2)

            if self._cancelled.is_set():
                raise Cancelled()
            yt_text = yt_err.text()
            if yt_rc != 0 and "ERROR:" in yt_text and "Broken pipe" not in yt_text:
                code, detail = classify_error(yt_text)
                raise ConversionError(code, detail or f"yt-dlp exited with {yt_rc}")
            if ff_rc != 0:
                raise ConversionError("ffmpeg", ff_err.text() or f"ffmpeg exited with {ff_rc}")
            if yt_rc != 0:
                code, detail = classify_error(yt_text)
                raise ConversionError(code, detail or f"yt-dlp exited with {yt_rc}")
            os.replace(req.part_path, req.out_path)
        except BaseException:
            _unlink(req.part_path)
            raise
        finally:
            if meta_path is not None:
                _unlink(meta_path)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_converter.py` → tous `passed` (le test `test_cancel_kills_real_processes` prend ≈ 0,5 s).

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/converter.py tests/test_converter.py && git commit -m "feat: streaming yt-dlp to ffmpeg conversion with progress and cancel"
```

---

### Task 9 : `jobqueue.py`

**Files:**
- Create: `bookmallow/jobqueue.py`
- Test: `tests/test_jobqueue.py`

**Interfaces:**
- Consumes: `Config` (T2), `Job/Status/new_job/now_iso` (T5), `StateStore` (T5), `retention` (T6), `names` (T4), `metadata.fetch_video`/`MetadataError`/`VideoMeta` (T7), `Conversion/ConvertRequest/ConversionError/Cancelled` (T8).
- Produces: `MB = 1024 * 1024`, `class DuplicateJob(Exception)` (attribut `job`), `estimate_bytes(duration: int | None, quality: str) -> int`, `class JobQueue(config, store, *, fetch_video=metadata.fetch_video, conversion_factory=Conversion, disk_usage=shutil.disk_usage)` avec `recover() -> None`, `start() -> None` (recover + thread démon), `submit(url, video_id, quality) -> Job`, `get(job_id) -> Job | None`, `cancel(job_id) -> bool`, `snapshot() -> list[dict]`, `process_next(block=True, timeout=None) -> bool`.
- Codes d'erreur ajoutés : `no_space`, `too_long`, `interrupted`, `internal`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_jobqueue.py` :
```python
from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from bookmallow import jobqueue as jq
from bookmallow.converter import Cancelled, ConversionError
from bookmallow.jobs import Status, new_job
from bookmallow.metadata import MetadataError, VideoMeta
from bookmallow.state import StateStore

Usage = namedtuple("Usage", "total used free")
URL = "https://www.youtube.com/watch?v=aaaaaaaaaaa"


def meta_for(url):
    vid = url[-11:]
    return VideoMeta(video_id=vid, title=f"Titre {vid}", duration=3600, thumbnail="https://i/x.jpg", channel="Chaîne", chapters=[])


class FakeConversion:
    instances: list["FakeConversion"] = []
    behaviour = "ok"  # "ok" | "fail" | "cancel"

    def __init__(self, req, on_progress=None):
        self.req = req
        self.on_progress = on_progress or (lambda p: None)
        self.cancelled = False
        FakeConversion.instances.append(self)

    def run(self):
        self.on_progress(42.0)
        if FakeConversion.behaviour == "fail":
            raise ConversionError("ffmpeg", "boom")
        if FakeConversion.behaviour == "cancel" or self.cancelled:
            raise Cancelled()
        self.req.out_path.write_bytes(b"x" * 1000)

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def q(config):
    FakeConversion.instances = []
    FakeConversion.behaviour = "ok"
    store = StateStore(config.state_path)
    queue = jq.JobQueue(config, store, fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    return queue


def test_estimate_bytes():
    assert jq.estimate_bytes(None, "64") == 0
    assert jq.estimate_bytes(3600, "64") == int(3600 * 64 * 1000 / 8 * 1.1)
    assert jq.estimate_bytes(3600, "192") == 3 * jq.estimate_bytes(3600, "64")


def test_submit_then_process_produces_file(q, config):
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    assert job.status is Status.QUEUED
    assert q.process_next(block=False) is True
    job = q.get(job.id)
    assert job.status is Status.DONE
    assert job.title == "Titre aaaaaaaaaaa" and job.duration == 3600 and job.channel == "Chaîne"
    assert job.filename == "Titre aaaaaaaaaaa [aaaaaaaaaaa].mp3"
    assert (config.data_dir / job.filename).stat().st_size == 1000
    assert job.size_bytes == 1000 and job.progress == 100.0
    assert job.started_at and job.finished_at
    assert q.process_next(block=False) is False
    assert FakeConversion.instances[0].req.quality == "64"
    assert StateStore(config.state_path).load()[0].status is Status.DONE


def test_duplicate_active_video_is_refused(q):
    first = q.submit(URL, "aaaaaaaaaaa", "64")
    with pytest.raises(jq.DuplicateJob) as exc:
        q.submit(URL, "aaaaaaaaaaa", "128")
    assert exc.value.job.id == first.id
    q.process_next(block=False)
    q.submit(URL, "aaaaaaaaaaa", "128")  # allowed again once finished


def test_fifo_order(q):
    ids = [q.submit(URL[:-11] + f"{c * 11}", c * 11, "64").id for c in "abc"]
    for expected in ids:
        q.process_next(block=False)
        done = [j for j in q.jobs if j.status is Status.DONE]
        assert done[-1].id == expected


def test_metadata_error_fails_job(q):
    q._fetch_video = lambda url: (_ for _ in ()).throw(MetadataError("private", "Private video"))
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.process_next(block=False)
    job = q.get(job.id)
    assert job.status is Status.FAILED and job.error_code == "private" and job.error == "Private video"


def test_conversion_error_fails_job(q):
    FakeConversion.behaviour = "fail"
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.process_next(block=False)
    assert q.get(job.id).status is Status.FAILED
    assert q.get(job.id).error_code == "ffmpeg"


def test_disk_guard(config):
    config = config.__class__(**{**config.__dict__, "min_free_mb": 100})
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**9, 0, 120 * jq.MB))
    queue.recover()
    job = queue.submit(URL, "aaaaaaaaaaa", "64")  # needs ~31 MB, leaves 89 MB < 100 MB
    queue.process_next(block=False)
    assert queue.get(job.id).status is Status.FAILED
    assert queue.get(job.id).error_code == "no_space"
    assert FakeConversion.instances == []


def test_duration_guard(config):
    config = config.__class__(**{**config.__dict__, "max_duration_hours": 0.5})
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    job = queue.submit(URL, "aaaaaaaaaaa", "64")
    queue.process_next(block=False)
    assert queue.get(job.id).error_code == "too_long"


def test_no_duration_limit_by_default(q):
    q._fetch_video = lambda url: VideoMeta("aaaaaaaaaaa", "Long", 17 * 3600, None, None, [])
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.process_next(block=False)
    assert q.get(job.id).status is Status.DONE


def test_cancel_queued_job(q):
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    assert q.cancel(job.id) is True
    assert q.get(job.id).status is Status.CANCELLED
    assert q.process_next(block=False) is True  # popped and skipped
    assert FakeConversion.instances == []
    assert q.cancel(job.id) is False
    assert q.cancel("nope") is False


def test_cancel_during_conversion(q):
    job = q.submit(URL, "aaaaaaaaaaa", "64")

    def fetch(url):
        # cancel while the worker is between fetching and converting
        q.cancel(job.id)
        return meta_for(url)

    q._fetch_video = fetch
    q.process_next(block=False)
    assert q.get(job.id).status is Status.CANCELLED
    assert FakeConversion.instances == []


def test_retention_runs_after_each_job(config):
    config = config.__class__(**{**config.__dict__, "max_files": 2})
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    import os, time
    for i, c in enumerate("abc"):
        queue.submit(URL[:-11] + c * 11, c * 11, "64")
        queue.process_next(block=False)
        path = config.data_dir / f"Titre {c * 11} [{c * 11}].mp3"
        if path.exists():
            t = 1_700_000_000 + i  # in the past, increasing: a < b < c
            os.utime(path, (t, t))
    names = sorted(p.name for p in config.data_dir.glob("*.mp3"))
    assert names == ["Titre bbbbbbbbbbb [bbbbbbbbbbb].mp3", "Titre ccccccccccc [ccccccccccc].mp3"]


def test_recover_marks_interrupted_requeues_and_cleans(config):
    store = StateStore(config.state_path)
    converting = new_job(URL, "aaaaaaaaaaa", "64"); converting.status = Status.CONVERTING
    queued_late = new_job(URL[:-11] + "b" * 11, "b" * 11, "64"); queued_late.created_at = "2026-02-01T00:00:00+00:00"
    queued_early = new_job(URL[:-11] + "c" * 11, "c" * 11, "64"); queued_early.created_at = "2026-01-01T00:00:00+00:00"
    store.save([converting, queued_late, queued_early])
    (config.data_dir / "wip.part.mp3").write_bytes(b"x")
    queue = jq.JobQueue(config, store, fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11))
    queue.recover()
    assert queue.get(converting.id).status is Status.FAILED
    assert queue.get(converting.id).error_code == "interrupted"
    assert not (config.data_dir / "wip.part.mp3").exists()
    queue.process_next(block=False)
    assert queue.get(queued_early.id).status is Status.DONE
    assert queue.get(queued_late.id).status is Status.QUEUED


def test_snapshot_is_plain_dicts(q):
    q.submit(URL, "aaaaaaaaaaa", "64")
    snap = q.snapshot()
    assert isinstance(snap, list) and snap[0]["status"] == "queued"


def test_start_runs_worker_thread(q, config):
    import time
    job = q.submit(URL, "aaaaaaaaaaa", "64")
    q.start()
    deadline = time.monotonic() + 3
    while q.get(job.id).status is not Status.DONE and time.monotonic() < deadline:
        time.sleep(0.02)
    assert q.get(job.id).status is Status.DONE
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_jobqueue.py` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/jobqueue.py` :
```python
"""Single-worker FIFO queue driving metadata fetch, conversion and retention (spec §6.2–6.8)."""
from __future__ import annotations

import logging
import queue
import shutil
import threading
from typing import Callable

from . import metadata as md
from . import names, retention
from .config import QUALITIES, Config
from .converter import Cancelled, Conversion, ConversionError, ConvertRequest
from .jobs import Job, Status, new_job, now_iso
from .state import StateStore

log = logging.getLogger(__name__)
MB = 1024 * 1024


class DuplicateJob(Exception):
    def __init__(self, job: Job):
        super().__init__(f"video {job.video_id} is already queued")
        self.job = job


def estimate_bytes(duration: int | None, quality: str) -> int:
    if not duration:
        return 0
    return int(duration * QUALITIES[quality]["kbps"] * 1000 / 8 * 1.1)


class JobQueue:
    def __init__(self, config: Config, store: StateStore, *,
                 fetch_video: Callable[[str], md.VideoMeta] = md.fetch_video,
                 conversion_factory=Conversion,
                 disk_usage=shutil.disk_usage):
        self.config = config
        self.store = store
        self._fetch_video = fetch_video
        self._conversion_factory = conversion_factory
        self._disk_usage = disk_usage
        self.jobs: list[Job] = []
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.RLock()
        self._current: Conversion | None = None
        self._current_id: str | None = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------------------------

    def recover(self) -> None:
        """Reload state.json, fail interrupted jobs, requeue queued ones, clean partials (spec §6.8)."""
        with self._lock:
            self.jobs = self.store.load()
            for job in self.jobs:
                if job.status in (Status.FETCHING, Status.CONVERTING):
                    job.status = Status.FAILED
                    job.error_code = "interrupted"
                    job.error = "interrupted by a restart"
                    job.finished_at = now_iso()
            for job in sorted((j for j in self.jobs if j.status is Status.QUEUED), key=lambda j: j.created_at):
                self._pending.put(job.id)
            for path in retention.remove_partials(self.config.data_dir):
                log.info("removed partial file %s", path.name)
            for path in retention.prune(self.config.data_dir, self.config.max_files):
                log.info("retention: deleted %s", path.name)
            self._save()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._work, name="bookmallow-worker", daemon=True)
        self._thread.start()

    # ---- public API ------------------------------------------------------------------------

    def submit(self, url: str, video_id: str, quality: str) -> Job:
        with self._lock:
            for existing in self.jobs:
                if existing.video_id == video_id and existing.is_active:
                    raise DuplicateJob(existing)
            job = new_job(url, video_id, quality)
            self.jobs.append(job)
            self._pending.put(job.id)
            self._save()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None or not job.is_active:
                return False
            job.status = Status.CANCELLED
            job.finished_at = now_iso()
            self._save()
            conv = self._current if self._current_id == job_id else None
        if conv is not None:
            conv.cancel()
        return True

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self.jobs]

    # ---- worker ----------------------------------------------------------------------------

    def process_next(self, block: bool = True, timeout: float | None = None) -> bool:
        """Take one queued job and run it to completion. Returns False if nothing was pending."""
        try:
            job_id = self._pending.get(block=block, timeout=timeout)
        except queue.Empty:
            return False
        job = self.get(job_id)
        if job is None or job.status is not Status.QUEUED:
            return True
        try:
            self._process(job)
        except Exception:  # noqa: BLE001 - the worker must survive anything
            log.exception("job %s crashed", job.id)
            self._fail(job, "internal", "unexpected error, see server logs")
        return True

    def _work(self) -> None:
        while True:
            try:
                self.process_next()
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")

    def _process(self, job: Job) -> None:
        with self._lock:
            job.status = Status.FETCHING
            job.started_at = now_iso()
            self._save()
        try:
            meta = self._fetch_video(job.url)
        except md.MetadataError as exc:
            self._fail(job, exc.code, exc.detail)
            return
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            job.title, job.duration = meta.title, meta.duration
            job.thumbnail, job.channel = meta.thumbnail, meta.channel
            reason = self._guard(job)
        if reason is not None:
            self._fail(job, *reason)
            return

        out_path = self._target_path(job)
        req = ConvertRequest(url=job.url, quality=job.quality, out_path=out_path, duration=job.duration,
                             title=job.title, channel=job.channel, chapters=meta.chapters)
        conv = self._conversion_factory(req, on_progress=lambda p: self._progress(job, p))
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            self._current, self._current_id = conv, job.id
            job.status = Status.CONVERTING
            self._save()
        try:
            conv.run()
        except Cancelled:
            self._finish(job, Status.CANCELLED)
            return
        except ConversionError as exc:
            self._fail(job, exc.code, exc.detail)
            return
        finally:
            with self._lock:
                self._current, self._current_id = None, None

        with self._lock:
            job.filename = out_path.name
            job.size_bytes = out_path.stat().st_size if out_path.exists() else None
            job.progress = 100.0
            self._finish(job, Status.DONE)
            deleted = retention.prune(self.config.data_dir, self.config.max_files)
        for path in deleted:
            log.info("retention: deleted %s", path.name)

    def _guard(self, job: Job) -> tuple[str, str] | None:
        hours = self.config.max_duration_hours
        if hours > 0 and job.duration and job.duration > hours * 3600:
            return "too_long", f"longer than {hours:g} h"
        need = estimate_bytes(job.duration, job.quality)
        free = self._disk_usage(str(self.config.data_dir)).free
        if free - need < self.config.min_free_mb * MB:
            return "no_space", f"about {need // MB} MB needed, {free // MB} MB free"
        return None

    def _target_path(self, job: Job):
        existing = {p.name for p in self.config.data_dir.iterdir()}
        return self.config.data_dir / names.unique_name(names.safe_filename(job.title, job.video_id), existing)

    def _progress(self, job: Job, percent: float) -> None:
        with self._lock:
            if job.status is Status.CONVERTING:
                job.progress = round(percent, 1)

    def _fail(self, job: Job, code: str, detail: str) -> None:
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            job.error_code, job.error = code, detail
            self._finish(job, Status.FAILED)

    def _finish(self, job: Job, status: Status) -> None:
        with self._lock:
            job.status = status
            job.finished_at = now_iso()
            self._save()

    def _save(self) -> None:
        with self._lock:
            self.jobs = self.store.save(self.jobs)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_jobqueue.py` → tous `passed`. Puis toute la suite : `.venv/bin/pytest` → tous `passed`.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/jobqueue.py tests/test_jobqueue.py && git commit -m "feat: single-worker job queue with guards, cancel and recovery"
```

---

### Task 10 : `auth.py` et `app.py` (routes et API)

**Files:**
- Create: `bookmallow/auth.py`, `bookmallow/app.py`, `wsgi.py`
- Create (minimal, remplacé en Task 11) : `bookmallow/templates/index.html`, `bookmallow/templates/login.html`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `Config`, `QUALITIES` (T2) ; `urls.parse/InvalidUrl/watch_url` (T3) ; `retention.list_mp3/next_to_go/PART_SUFFIX` (T6) ; `metadata.fetch_playlist/MetadataError/PlaylistMeta/PlaylistEntry` (T7) ; `JobQueue/DuplicateJob` (T9) ; `StateStore` (T5).
- Produces (`auth.py`) : `check_password(config, candidate: str) -> bool`, `is_authenticated(config) -> bool`, `login_required(view)`.
- Produces (`app.py`) : `create_app(config: Config | None = None, jobqueue: JobQueue | None = None, start_worker: bool = True, fetch_playlist=metadata.fetch_playlist) -> Flask` ; `build_state(config, q) -> dict` ; `resolve_file(data_dir: Path, name: str) -> str | None` ; la queue est accessible via `app.extensions["jobqueue"]` ; la config via `app.config["BOOKMALLOW"]`.
- Contrat JSON de `/api/state` :
  ```json
  {"jobs": [Job.to_dict() + "expired": bool],
   "files": [{"name","size_bytes","modified_at","title","thumbnail","channel","duration","quality","job_id"}],
   "retention": {"max_files": 6, "count": 2, "next_to_go": "…mp3" | null},
   "config": {"max_files": 6, "qualities": ["64","128","192"], "default_quality": "64", "default_lang": "fr", "auth_enabled": false}}
  ```
- Contrat de `POST /api/jobs` : corps `{"url", "quality"?, "playlist"?: "expand"|"ignore", "video_ids"?: [..]}` → `201 {"jobs": [...], "skipped": [...]}` | `200 {"playlist": {"id","title","count","entries":[{"video_id","title","duration"}],"max_files","single_video_url"}}` | `400 {"error": "invalid_url"|"bad_quality"}` | `409 {"error": "duplicate", "jobs": [...]}` | `502 {"error": "metadata", "code", "detail"}`.

- [ ] **Step 1 : Écrire les tests**

`tests/test_app.py` :
```python
from __future__ import annotations

from dataclasses import replace

import pytest

from bookmallow.app import build_state, create_app, resolve_file
from bookmallow.jobqueue import JobQueue
from bookmallow.jobs import Status, new_job
from bookmallow.metadata import MetadataError, PlaylistEntry, PlaylistMeta
from bookmallow.state import StateStore

WATCH = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def fake_playlist(url):
    return PlaylistMeta("PL1", "Ma liste", [PlaylistEntry(c * 11, f"Partie {c}", 10) for c in "abcdefgh"])


def make_client(config, fetch_playlist=fake_playlist):
    q = JobQueue(config, StateStore(config.state_path), fetch_video=lambda u: None, conversion_factory=None)
    q.recover()
    app = create_app(config, jobqueue=q, start_worker=False, fetch_playlist=fetch_playlist)
    app.config["TESTING"] = True
    client = app.test_client()
    client.queue = q
    return client


@pytest.fixture
def client(config):
    return make_client(config)


@pytest.fixture
def auth_client(config):
    return make_client(replace(config, app_password="pink"))


def test_healthz(client):
    assert client.get("/healthz").get_json() == {"ok": True}


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Bookmallow" in r.data


def test_state_shape(client, config):
    (config.data_dir / "Old [aaaaaaaaaaa].mp3").write_bytes(b"x" * 10)
    d = client.get("/api/state").get_json()
    assert d["jobs"] == []
    f = d["files"][0]
    assert f["name"] == "Old [aaaaaaaaaaa].mp3" and f["size_bytes"] == 10 and f["title"] == "Old [aaaaaaaaaaa]"
    assert f["thumbnail"] is None and f["job_id"] is None and f["modified_at"].endswith("+00:00")
    assert d["retention"] == {"max_files": 6, "count": 1, "next_to_go": None}
    assert d["config"] == {"max_files": 6, "qualities": ["64", "128", "192"], "default_quality": "64",
                           "default_lang": "fr", "auth_enabled": False}


def test_state_joins_done_jobs_and_flags_expired(client, config):
    q = client.queue
    done = new_job(WATCH, "dQw4w9WgXcQ", "128")
    done.status, done.title, done.thumbnail, done.filename = Status.DONE, "Livre", "https://i/x.jpg", "Livre [dQw4w9WgXcQ].mp3"
    gone = new_job(WATCH, "bbbbbbbbbbb", "64")
    gone.status, gone.filename = Status.DONE, "Gone [bbbbbbbbbbb].mp3"
    q.jobs.extend([done, gone])
    (config.data_dir / done.filename).write_bytes(b"x")
    d = client.get("/api/state").get_json()
    assert d["files"][0]["title"] == "Livre" and d["files"][0]["thumbnail"] == "https://i/x.jpg"
    assert d["files"][0]["quality"] == "128" and d["files"][0]["job_id"] == done.id
    by_id = {j["id"]: j for j in d["jobs"]}
    assert by_id[done.id]["expired"] is False and by_id[gone.id]["expired"] is True


def test_submit_video(client):
    r = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ", "quality": "128"})
    assert r.status_code == 201
    job = r.get_json()["jobs"][0]
    assert job["video_id"] == "dQw4w9WgXcQ" and job["quality"] == "128" and job["status"] == "queued"
    assert job["url"] == WATCH
    assert client.queue.get(job["id"]) is not None


def test_submit_uses_default_quality(client):
    job = client.post("/api/jobs", json={"url": WATCH}).get_json()["jobs"][0]
    assert job["quality"] == "64"


def test_submit_rejects_bad_quality_and_url(client):
    assert client.post("/api/jobs", json={"url": WATCH, "quality": "320"}).status_code == 400
    r = client.post("/api/jobs", json={"url": "https://vimeo.com/1"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_url"
    assert client.post("/api/jobs", data="not json", content_type="text/plain").status_code == 400


def test_submit_duplicate(client):
    client.post("/api/jobs", json={"url": WATCH})
    r = client.post("/api/jobs", json={"url": WATCH})
    assert r.status_code == 409 and r.get_json()["error"] == "duplicate" and len(r.get_json()["jobs"]) == 1


def test_playlist_preview(client):
    r = client.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 200
    pl = r.get_json()["playlist"]
    assert pl["title"] == "Ma liste" and pl["count"] == 8 and pl["max_files"] == 6
    assert pl["single_video_url"] is None
    assert pl["entries"][0] == {"video_id": "aaaaaaaaaaa", "title": "Partie a", "duration": 10}


def test_playlist_preview_with_video_offers_single(client):
    r = client.post("/api/jobs", json={"url": WATCH + "&list=PL1"})
    assert r.get_json()["playlist"]["single_video_url"] == WATCH


def test_playlist_ignore_queues_single_video(client):
    r = client.post("/api/jobs", json={"url": WATCH + "&list=PL1", "playlist": "ignore"})
    assert r.status_code == 201 and r.get_json()["jobs"][0]["video_id"] == "dQw4w9WgXcQ"


def test_playlist_expand_is_capped_to_max_files(client):
    r = client.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1", "playlist": "expand"})
    assert r.status_code == 201
    assert [j["video_id"] for j in r.get_json()["jobs"]] == [c * 11 for c in "abcdef"]


def test_playlist_expand_selected_ids(client):
    r = client.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1", "playlist": "expand",
                                       "video_ids": ["ccccccccccc", "hhhhhhhhhhh", "zzzzzzzzzzz"]})
    assert [j["video_id"] for j in r.get_json()["jobs"]] == ["ccccccccccc", "hhhhhhhhhhh"]


def test_playlist_error(config):
    def boom(url):
        raise MetadataError("unavailable", "gone")
    c = make_client(config, fetch_playlist=boom)
    r = c.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 502 and r.get_json() == {"error": "metadata", "code": "unavailable", "detail": "gone"}


def test_cancel_job(client):
    job = client.post("/api/jobs", json={"url": WATCH}).get_json()["jobs"][0]
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert client.queue.get(job["id"]).status is Status.CANCELLED
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 404


def test_download_file(client, config):
    (config.data_dir / "Livre [dQw4w9WgXcQ].mp3").write_bytes(b"0123456789")
    r = client.get("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3")
    assert r.status_code == 200 and r.data == b"0123456789"
    assert "attachment" in r.headers["Content-Disposition"]
    r = client.get("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.data == b"0123"


def test_download_refuses_missing_traversal_and_non_mp3(client, config):
    (config.data_dir.parent / "secret.mp3").write_bytes(b"s")
    (config.data_dir / "wip.part.mp3").write_bytes(b"w")
    assert client.get("/api/files/..%2Fsecret.mp3").status_code == 404
    assert client.get("/api/files/nope.mp3").status_code == 404
    assert client.get("/api/files/state.json").status_code == 404
    assert client.get("/api/files/wip.part.mp3").status_code == 404


def test_resolve_file(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"a")
    assert resolve_file(tmp_path, "a.mp3") == "a.mp3"
    assert resolve_file(tmp_path, "b.mp3") is None
    assert resolve_file(tmp_path, "../a.mp3") is None
    assert resolve_file(tmp_path, "a.mp3/") is None


def test_delete_file(client, config):
    p = config.data_dir / "Livre [dQw4w9WgXcQ].mp3"
    p.write_bytes(b"x")
    assert client.delete("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3").status_code == 204
    assert not p.exists()
    assert client.delete("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3").status_code == 404


def test_login_page_redirects_when_auth_disabled(client):
    r = client.get("/login")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


def test_auth_pages_redirect_and_api_401(auth_client):
    r = auth_client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = auth_client.get("/api/state")
    assert r.status_code == 401 and r.get_json() == {"error": "unauthorized"}
    assert auth_client.post("/api/jobs", json={"url": WATCH}).status_code == 401


def test_auth_login_flow(auth_client):
    assert auth_client.post("/login", data={"password": "nope"}).status_code == 401
    r = auth_client.post("/login?next=/", data={"password": "pink"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert auth_client.get("/").status_code == 200
    assert auth_client.get("/api/state").status_code == 200
    r = auth_client.post("/logout")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert auth_client.get("/api/state").status_code == 401


def test_auth_open_redirect_blocked(auth_client):
    r = auth_client.post("/login?next=//evil.com/x", data={"password": "pink"})
    assert r.headers["Location"] in ("/", "http://localhost/")
    r = auth_client.post("/login?next=https://evil.com", data={"password": "pink"})
    assert r.headers["Location"] in ("/", "http://localhost/")


def test_build_state_direct(config, client):
    d = build_state(config, client.queue)
    assert set(d) == {"jobs", "files", "retention", "config"}
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_app.py` → FAIL.

- [ ] **Step 3 : Implémenter `auth.py`**

`bookmallow/auth.py` :
```python
"""Optional shared-password protection (spec §8)."""
from __future__ import annotations

import hmac
from functools import wraps

from flask import current_app, jsonify, redirect, request, session, url_for

from .config import Config


def check_password(config: Config, candidate: str) -> bool:
    if not config.auth_enabled:
        return False
    return hmac.compare_digest(config.app_password.encode("utf-8"), (candidate or "").encode("utf-8"))


def is_authenticated(config: Config) -> bool:
    return (not config.auth_enabled) or bool(session.get("ok"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        config: Config = current_app.config["BOOKMALLOW"]
        if is_authenticated(config):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="unauthorized"), 401
        return redirect(url_for("login", next=request.path))
    return wrapped
```

- [ ] **Step 4 : Implémenter `app.py`**

`bookmallow/app.py` :
```python
"""Flask application: pages, JSON API, downloads (spec §7)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from . import __version__
from . import config as cfg
from . import metadata as md
from . import retention, urls
from .auth import check_password, is_authenticated, login_required
from .config import QUALITIES, Config
from .jobqueue import DuplicateJob, JobQueue
from .state import StateStore

log = logging.getLogger(__name__)
PLAYLIST_PREVIEW_LIMIT = 200


def resolve_file(data_dir: Path, name: str) -> str | None:
    """Return `name` only if it is exactly the name of a finished MP3 sitting in data_dir."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if not name.endswith(".mp3") or name.endswith(retention.PART_SUFFIX):
        return None
    return name if name in os.listdir(data_dir) else None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat()


def build_state(config: Config, q: JobQueue) -> dict:
    jobs = q.snapshot()
    files = retention.list_mp3(config.data_dir)
    existing = {p.name for p in files}
    by_name: dict[str, dict] = {}
    for job in jobs:
        if job["status"] == "done":
            present = job["filename"] in existing
            job["expired"] = not present
            if present:
                by_name.setdefault(job["filename"], job)
        else:
            job["expired"] = False
    files_out = []
    for path in files:
        st = path.stat()
        job = by_name.get(path.name)
        files_out.append({
            "name": path.name,
            "size_bytes": st.st_size,
            "modified_at": _iso(st.st_mtime),
            "title": job["title"] if job and job["title"] else path.stem,
            "thumbnail": job["thumbnail"] if job else None,
            "channel": job["channel"] if job else None,
            "duration": job["duration"] if job else None,
            "quality": job["quality"] if job else None,
            "job_id": job["id"] if job else None,
        })
    return {
        "jobs": jobs,
        "files": files_out,
        "retention": {
            "max_files": config.max_files,
            "count": len(files),
            "next_to_go": retention.next_to_go(config.data_dir, config.max_files),
        },
        "config": {
            "max_files": config.max_files,
            "qualities": list(QUALITIES),
            "default_quality": config.default_quality,
            "default_lang": config.default_lang,
            "auth_enabled": config.auth_enabled,
        },
    }


def _safe_next(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("index")


def _submit(config: Config, q: JobQueue, fetch_playlist):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid_url", detail="body must be JSON"), 400
    quality = str(data.get("quality") or config.default_quality)
    if quality not in QUALITIES:
        return jsonify(error="bad_quality"), 400
    try:
        parsed = urls.parse(str(data.get("url") or ""))
    except urls.InvalidUrl as exc:
        return jsonify(error="invalid_url", detail=str(exc)), 400

    mode = data.get("playlist")
    if parsed.is_playlist and mode != "ignore":
        try:
            playlist = fetch_playlist(parsed.playlist_url)
        except md.MetadataError as exc:
            return jsonify(error="metadata", code=exc.code, detail=exc.detail), 502
        if mode != "expand":
            return jsonify(playlist={
                "id": playlist.playlist_id,
                "title": playlist.title,
                "count": len(playlist.entries),
                "entries": [{"video_id": e.video_id, "title": e.title, "duration": e.duration}
                            for e in playlist.entries[:PLAYLIST_PREVIEW_LIMIT]],
                "max_files": config.max_files,
                "single_video_url": parsed.watch_url if parsed.video_id else None,
            })
        wanted = data.get("video_ids")
        wanted_set = set(map(str, wanted)) if isinstance(wanted, list) and wanted else None
        entries = [e for e in playlist.entries if wanted_set is None or e.video_id in wanted_set]
        targets = [(urls.watch_url(e.video_id), e.video_id) for e in entries[:config.max_files]]
    else:
        if parsed.video_id is None:
            return jsonify(error="invalid_url", detail="no_id"), 400
        targets = [(parsed.watch_url, parsed.video_id)]

    created, skipped = [], []
    for url, video_id in targets:
        try:
            created.append(q.submit(url, video_id, quality).to_dict())
        except DuplicateJob as exc:
            skipped.append(exc.job.to_dict())
    if not created and skipped:
        return jsonify(error="duplicate", jobs=skipped), 409
    return jsonify(jobs=created, skipped=skipped), 201


def create_app(config: Config | None = None, jobqueue: JobQueue | None = None, start_worker: bool = True,
               fetch_playlist=md.fetch_playlist) -> Flask:
    config = config or cfg.load()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.force_https,
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
        MAX_CONTENT_LENGTH=64 * 1024,
        BOOKMALLOW=config,
    )
    if jobqueue is None:
        jobqueue = JobQueue(config, StateStore(config.state_path))
        jobqueue.recover()
    q = jobqueue
    if start_worker:
        q.start()
    app.extensions["jobqueue"] = q

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.get("/")
    @login_required
    def index():
        return render_template("index.html", config=config, version=__version__)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if is_authenticated(config):
            return redirect(url_for("index"))
        error = False
        if request.method == "POST":
            if check_password(config, request.form.get("password", "")):
                session.clear()
                session["ok"] = True
                session.permanent = True
                return redirect(_safe_next(request.args.get("next")))
            error = True
        return render_template("login.html", error=error, lang=config.default_lang), (401 if error else 200)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login") if config.auth_enabled else url_for("index"))

    @app.get("/api/state")
    @login_required
    def api_state():
        return jsonify(build_state(config, q))

    @app.post("/api/jobs")
    @login_required
    def api_submit():
        return _submit(config, q, fetch_playlist)

    @app.delete("/api/jobs/<job_id>")
    @login_required
    def api_cancel(job_id: str):
        if not q.cancel(job_id):
            return jsonify(error="not_found"), 404
        return "", 204

    @app.get("/api/files/<path:name>")
    @login_required
    def api_download(name: str):
        real = resolve_file(config.data_dir, name)
        if real is None:
            return jsonify(error="not_found"), 404
        return send_from_directory(config.data_dir, real, as_attachment=True, conditional=True, max_age=0)

    @app.delete("/api/files/<path:name>")
    @login_required
    def api_delete_file(name: str):
        real = resolve_file(config.data_dir, name)
        if real is None:
            return jsonify(error="not_found"), 404
        (config.data_dir / real).unlink(missing_ok=True)
        log.info("deleted %s on request", real)
        return "", 204

    return app
```

Templates minimaux pour que `render_template` fonctionne (remplacés en Task 11) :

`bookmallow/templates/index.html` :
```html
<!doctype html><html lang="{{ config.default_lang }}"><head><meta charset="utf-8"><title>Bookmallow</title></head>
<body><h1>Bookmallow</h1><p>v{{ version }}</p></body></html>
```

`bookmallow/templates/login.html` :
```html
<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8"><title>Bookmallow</title></head>
<body><h1>Bookmallow</h1><form method="post"><input name="password" type="password"><button>OK</button></form>
{% if error %}<p>Wrong password.</p>{% endif %}</body></html>
```

`wsgi.py` (racine) :
```python
"""Gunicorn entry point: `gunicorn wsgi:app`."""
from __future__ import annotations

import logging
import os

from bookmallow.app import create_app

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app = create_app()
```

- [ ] **Step 5 : Vérifier** — `.venv/bin/pytest tests/test_app.py` → tous `passed`, puis `.venv/bin/pytest` → tous `passed`.

- [ ] **Step 6 : Commit**

```bash
git add bookmallow/auth.py bookmallow/app.py bookmallow/templates wsgi.py tests/test_app.py && git commit -m "feat: Flask app with JSON API, downloads and optional password"
```

---

### Task 11 : Interface web (templates + static)

**Files:**
- Modify: `bookmallow/templates/index.html`, `bookmallow/templates/login.html`
- Create: `bookmallow/static/style.css`, `bookmallow/static/app.js`, `bookmallow/static/logo.svg`
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `/api/state`, `POST /api/jobs`, `DELETE /api/jobs/<id>`, `GET|DELETE /api/files/<name>` (T10) ; variables de template `config` (`default_lang`, `default_quality`, `max_files`, `auth_enabled`) et `version`.
- Produces : une page unique, FR/EN (localStorage `bookmallow.lang`), qualité mémorisée (localStorage `bookmallow.quality`), polling 2 s si un job est actif sinon 10 s.

- [ ] **Step 1 : Écrire le test**

`tests/test_frontend.py` :
```python
from __future__ import annotations

import re
from pathlib import Path

from bookmallow.app import create_app
from bookmallow.jobqueue import JobQueue
from bookmallow.state import StateStore

ROOT = Path(__file__).resolve().parents[1] / "bookmallow"


def client(config):
    q = JobQueue(config, StateStore(config.state_path))
    q.recover()
    app = create_app(config, jobqueue=q, start_worker=False)
    return app.test_client()


def test_index_has_hooks_and_static_assets(config):
    c = client(config)
    html = c.get("/").get_data(as_text=True)
    for hook in ('id="submit-form"', 'id="url"', 'id="qualities"', 'id="banner"', 'id="jobs"', 'id="files"',
                 'id="playlist-dialog"', 'id="lang-toggle"', 'data-default-quality="64"', 'data-max-files="6"'):
        assert hook in html
    assert 'action="/logout"' not in html  # auth disabled → no logout button
    for asset in ("/static/style.css", "/static/app.js", "/static/logo.svg"):
        assert asset in html
        assert c.get(asset).status_code == 200


def test_no_external_resources():
    pattern = re.compile(r'(?:src|href)=["\']https?://', re.I)
    for path in list((ROOT / "templates").glob("*.html")) + [ROOT / "static" / "app.js"]:
        text = path.read_text(encoding="utf-8")
        hits = [m for m in pattern.finditer(text) if "github.com/clemdepernet/bookmallow" not in text[m.start():m.start() + 80]]
        assert hits == [], f"{path.name} loads an external resource"
    assert "@import" not in (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_palette_tokens_present():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    for color in ("#FFF7F9", "#F8C8D8", "#E75A8C", "#C9B6F2", "#BDEBD5", "#F49A8B", "#4A2A3C"):
        assert color.lower() in css.lower()


def test_i18n_has_both_languages_with_same_keys():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    fr = re.search(r"\n    fr: \{(.*?)\n    \},", js, re.S).group(1)
    en = re.search(r"\n    en: \{(.*?)\n    \},", js, re.S).group(1)
    keys = lambda block: set(re.findall(r"^\s+(\w+):", block, re.M))  # noqa: E731
    assert keys(fr) == keys(en) and len(keys(fr)) > 40
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_frontend.py` → FAIL.

- [ ] **Step 3 : Écrire `logo.svg`**

`bookmallow/static/logo.svg` :
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FDE7EE"/><stop offset="1" stop-color="#F8C8D8"/>
    </linearGradient>
  </defs>
  <path d="M22 50 C22 26 74 26 74 50" fill="none" stroke="#C9B6F2" stroke-width="7" stroke-linecap="round"/>
  <rect x="24" y="36" width="48" height="44" rx="16" fill="url(#g)" stroke="#E75A8C" stroke-width="2.5"/>
  <ellipse cx="48" cy="38" rx="24" ry="8" fill="#FFF7F9" stroke="#E75A8C" stroke-width="2.5"/>
  <rect x="13" y="46" width="13" height="19" rx="6.5" fill="#C9B6F2" stroke="#4A2A3C" stroke-width="2"/>
  <rect x="70" y="46" width="13" height="19" rx="6.5" fill="#C9B6F2" stroke="#4A2A3C" stroke-width="2"/>
  <circle cx="40" cy="58" r="2.6" fill="#4A2A3C"/><circle cx="56" cy="58" r="2.6" fill="#4A2A3C"/>
  <path d="M42 66 Q48 71 54 66" fill="none" stroke="#4A2A3C" stroke-width="2.4" stroke-linecap="round"/>
  <circle cx="34" cy="64" r="3" fill="#F49A8B" opacity=".7"/><circle cx="62" cy="64" r="3" fill="#F49A8B" opacity=".7"/>
  <path d="M80 14l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" fill="#E75A8C"/>
  <path d="M14 22l1.3 3.2 3.2 1.3-3.2 1.3-1.3 3.2-1.3-3.2-3.2-1.3 3.2-1.3z" fill="#C9B6F2"/>
</svg>
```

- [ ] **Step 4 : Écrire `index.html`**

`bookmallow/templates/index.html` :
```html
<!doctype html>
<html lang="{{ config.default_lang }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Bookmallow</title>
  <link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='logo.svg') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body data-default-lang="{{ config.default_lang }}" data-default-quality="{{ config.default_quality }}" data-max-files="{{ config.max_files }}">
  <header class="top">
    <a class="brand" href="/">
      <img class="logo" src="{{ url_for('static', filename='logo.svg') }}" alt="" width="56" height="56">
      <span class="brand-text"><strong>Bookmallow</strong><small data-i18n="tagline"></small></span>
    </a>
    <nav class="top-actions">
      <button id="lang-toggle" class="chip" type="button" aria-label="Language / Langue"></button>
      {% if config.auth_enabled %}
      <form method="post" action="{{ url_for('logout') }}"><button class="chip" type="submit" data-i18n="logout"></button></form>
      {% endif %}
    </nav>
  </header>

  <main>
    <section class="card hero">
      <h1 data-i18n="hero_title"></h1>
      <p class="lead" data-i18n="hero_lead"></p>
      <form id="submit-form" novalidate>
        <label class="sr-only" for="url" data-i18n="url_label"></label>
        <div class="url-row">
          <input id="url" name="url" type="url" inputmode="url" autocomplete="off" spellcheck="false"
                 placeholder="https://www.youtube.com/watch?v=…" required>
          <button id="submit-btn" class="btn primary" type="submit"><span data-i18n="convert"></span> ✨</button>
        </div>
        <fieldset class="qualities" id="qualities">
          <legend data-i18n="quality"></legend>
        </fieldset>
      </form>
      <p id="form-msg" class="form-msg" role="status" aria-live="polite"></p>
    </section>

    <aside id="banner" class="banner" role="note"></aside>

    <section class="card">
      <h2><span data-i18n="queue"></span> <span id="queue-count" class="count"></span></h2>
      <ul id="jobs" class="cards" aria-live="polite"></ul>
      <p id="jobs-empty" class="empty" data-i18n="queue_empty"></p>
    </section>

    <section class="card">
      <h2><span data-i18n="library"></span> <span id="files-count" class="count"></span></h2>
      <ul id="files" class="cards"></ul>
      <p id="files-empty" class="empty" data-i18n="library_empty"></p>
    </section>
  </main>

  <footer>
    <span>Bookmallow v{{ version }}</span> ·
    <a href="https://github.com/clemdepernet/bookmallow" rel="noopener" target="_blank">GitHub</a> ·
    <span data-i18n="footer"></span>
  </footer>

  <dialog id="playlist-dialog" class="dialog">
    <div class="dialog-body">
      <h3 id="pl-title"></h3>
      <p id="pl-intro" class="muted"></p>
      <ul id="pl-entries" class="pl-entries"></ul>
      <p id="pl-note" class="note"></p>
      <div class="dialog-actions">
        <button type="button" class="btn ghost" id="pl-cancel" data-i18n="cancel"></button>
        <button type="button" class="btn ghost" id="pl-single" data-i18n="pl_single"></button>
        <button type="button" class="btn primary" id="pl-add"></button>
      </div>
    </div>
  </dialog>

  <div id="toasts" class="toasts" aria-live="polite"></div>
  <script src="{{ url_for('static', filename='app.js') }}" defer></script>
</body>
</html>
```

- [ ] **Step 5 : Écrire `login.html`**

`bookmallow/templates/login.html` :
```html
<!doctype html>
<html lang="{{ lang }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Bookmallow</title>
  <link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='logo.svg') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body class="login-page">
  <main class="card login-card">
    <img class="logo big" src="{{ url_for('static', filename='logo.svg') }}" alt="" width="96" height="96">
    <h1>Bookmallow</h1>
    <p class="lead">{% if lang == 'fr' %}Entre le mot de passe partagé pour continuer.{% else %}Enter the shared password to continue.{% endif %}</p>
    <form method="post" class="login-form">
      <label class="sr-only" for="password">{% if lang == 'fr' %}Mot de passe{% else %}Password{% endif %}</label>
      <input id="password" name="password" type="password" autocomplete="current-password" autofocus required>
      <button class="btn primary" type="submit">{% if lang == 'fr' %}Entrer 🎀{% else %}Enter 🎀{% endif %}</button>
    </form>
    {% if error %}<p class="form-msg error" role="alert">{% if lang == 'fr' %}Mot de passe incorrect.{% else %}Wrong password.{% endif %}</p>{% endif %}
  </main>
</body>
</html>
```

- [ ] **Step 6 : Écrire `style.css`**

`bookmallow/static/style.css` :
```css
:root {
  --cream: #FFF7F9;
  --pink: #F8C8D8;
  --pink-strong: #E75A8C;
  --lilac: #C9B6F2;
  --mint: #BDEBD5;
  --coral: #F49A8B;
  --plum: #4A2A3C;
  --pink-soft: #FDE7EE;
  --lilac-soft: #EFE9FB;
  --mint-soft: #E6F7EE;
  --coral-soft: #FDE8E4;
  --muted: #8A6F7D;
  --card: #FFFFFF;
  --border: #F3DCE5;
  --radius: 22px;
  --radius-sm: 14px;
  --shadow: 0 12px 32px rgba(231, 90, 140, 0.10);
  --font: ui-rounded, "Nunito", "Quicksand", "Segoe UI", system-ui, -apple-system, sans-serif;
}

* { box-sizing: border-box; }
html { color-scheme: light; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font);
  color: var(--plum);
  background:
    radial-gradient(circle at 8% 0%, var(--pink-soft), transparent 45%),
    radial-gradient(circle at 92% 18%, var(--lilac-soft), transparent 40%),
    var(--cream);
  line-height: 1.45;
}
a { color: var(--pink-strong); }
h1, h2, h3 { margin: 0 0 .5rem; letter-spacing: -.01em; }
h1 { font-size: clamp(1.6rem, 4vw, 2.2rem); }
h2 { font-size: 1.15rem; display: flex; align-items: center; gap: .5rem; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.muted { color: var(--muted); }

/* layout */
.top { max-width: 900px; margin: 0 auto; padding: 18px 16px 6px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
main { max-width: 900px; margin: 0 auto; padding: 8px 16px 40px; display: grid; gap: 18px; }
footer { text-align: center; color: var(--muted); font-size: .85rem; padding: 0 16px 28px; }

.brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: inherit; }
.brand-text { display: flex; flex-direction: column; line-height: 1.1; }
.brand-text strong { font-size: 1.25rem; }
.brand-text small { color: var(--muted); font-size: .8rem; }
.logo { width: 56px; height: 56px; filter: drop-shadow(0 4px 8px rgba(231, 90, 140, .25)); }
.logo.big { width: 96px; height: 96px; margin: 0 auto 8px; display: block; }
.top-actions { display: flex; gap: 8px; align-items: center; }
.top-actions form { margin: 0; }

/* cards */
.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); padding: 22px; }
.hero { background: linear-gradient(160deg, #FFFFFF 0%, var(--pink-soft) 100%); }
.lead { margin: 0 0 16px; color: var(--muted); }

/* form */
.url-row { display: flex; gap: 10px; flex-wrap: wrap; }
input[type="url"], input[type="password"] {
  flex: 1 1 260px; min-width: 0; font: inherit; padding: 13px 16px; border-radius: 999px;
  border: 2px solid var(--pink); background: #fff; color: var(--plum); outline: none; transition: border-color .15s, box-shadow .15s;
}
input[type="url"]:focus, input[type="password"]:focus { border-color: var(--pink-strong); box-shadow: 0 0 0 4px rgba(231, 90, 140, .15); }
.btn {
  font: inherit; font-weight: 700; border-radius: 999px; padding: 12px 20px; border: 2px solid transparent; cursor: pointer;
  transition: transform .08s ease, box-shadow .15s ease, background .15s ease;
}
.btn:active { transform: translateY(1px) scale(.99); }
.btn:focus-visible, .chip:focus-visible, input:focus-visible { outline: 3px solid var(--lilac); outline-offset: 2px; }
.btn.primary { background: var(--pink-strong); color: #fff; box-shadow: 0 8px 20px rgba(231, 90, 140, .3); }
.btn.primary:hover { background: #D94A7E; }
.btn.primary[disabled] { opacity: .6; cursor: progress; }
.btn.ghost { background: #fff; color: var(--plum); border-color: var(--pink); }
.btn.ghost:hover { background: var(--pink-soft); }
.btn.small { padding: 8px 14px; font-size: .9rem; }
.btn.danger { color: #B3362B; border-color: var(--coral); }
.btn.danger:hover { background: var(--coral-soft); }
.chip { font: inherit; font-weight: 700; font-size: .85rem; padding: 7px 12px; border-radius: 999px; border: 2px solid var(--lilac); background: var(--lilac-soft); color: var(--plum); cursor: pointer; }
.chip:hover { background: var(--lilac); }

.qualities { border: 0; padding: 0; margin: 14px 0 0; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.qualities legend { float: left; padding: 0; margin-right: 6px; font-weight: 700; font-size: .9rem; color: var(--muted); }
.quality { position: relative; }
.quality input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.quality label { display: inline-flex; flex-direction: column; padding: 8px 14px; border-radius: 16px; border: 2px solid var(--pink); background: #fff; cursor: pointer; transition: all .15s; }
.quality label b { font-size: .92rem; }
.quality label small { color: var(--muted); font-size: .72rem; }
.quality input:checked + label { background: var(--pink-soft); border-color: var(--pink-strong); box-shadow: 0 0 0 3px rgba(231, 90, 140, .12); }
.quality input:focus-visible + label { outline: 3px solid var(--lilac); outline-offset: 2px; }
.form-msg { min-height: 1.4em; margin: 10px 0 0; font-weight: 600; color: var(--muted); }
.form-msg.error { color: #B3362B; }
.form-msg.ok { color: #23795A; }

/* banner */
.banner { background: var(--lilac-soft); border: 1px dashed var(--lilac); color: var(--plum); border-radius: var(--radius-sm); padding: 12px 16px; font-weight: 600; }

/* lists */
.cards { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.count { font-size: .8rem; font-weight: 700; color: #fff; background: var(--lilac); border-radius: 999px; padding: 2px 9px; }
.count:empty { display: none; }
.empty { color: var(--muted); text-align: center; margin: 8px 0 0; }
.empty.hidden { display: none; }
.item { display: grid; grid-template-columns: 96px 1fr; gap: 14px; padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: #fff; align-items: start; }
.item.expired { opacity: .6; background: var(--cream); }
.thumb { width: 96px; height: 72px; border-radius: 12px; object-fit: cover; background: var(--pink-soft); display: grid; place-items: center; font-size: 1.6rem; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.item-body { min-width: 0; display: grid; gap: 6px; }
.item-title { font-weight: 700; overflow-wrap: anywhere; }
.item-meta { color: var(--muted); font-size: .85rem; display: flex; flex-wrap: wrap; gap: 4px 10px; }
.item-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 2px; }
.item-error { color: #B3362B; font-size: .9rem; }
.item-error small { display: block; color: var(--muted); }

.pill { display: inline-flex; align-items: center; gap: 6px; font-size: .78rem; font-weight: 700; padding: 3px 10px; border-radius: 999px; background: var(--lilac-soft); color: var(--plum); }
.pill.queued { background: var(--lilac-soft); }
.pill.fetching, .pill.converting { background: var(--pink-soft); color: var(--pink-strong); }
.pill.done { background: var(--mint-soft); color: #23795A; }
.pill.failed { background: var(--coral-soft); color: #B3362B; }
.pill.cancelled { background: #EEE; color: var(--muted); }
.pill .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.pill.converting .dot, .pill.fetching .dot { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }

.badge { display: inline-flex; font-size: .75rem; font-weight: 700; padding: 3px 9px; border-radius: 999px; background: var(--coral-soft); color: #B3362B; }

.progress { height: 12px; border-radius: 999px; background: var(--pink-soft); overflow: hidden; position: relative; }
.progress > span {
  display: block; height: 100%; border-radius: 999px; width: 0;
  background: linear-gradient(90deg, var(--pink-strong), var(--lilac), var(--pink-strong)); background-size: 200% 100%;
  animation: shimmer 2.2s linear infinite; transition: width .6s ease;
}
.progress.indeterminate > span { width: 40%; animation: slide 1.4s ease-in-out infinite; }
@keyframes shimmer { from { background-position: 0 0; } to { background-position: 200% 0; } }
@keyframes slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
.progress-label { font-size: .8rem; color: var(--muted); font-weight: 700; }

/* dialog */
.dialog { border: 0; border-radius: var(--radius); padding: 0; max-width: 560px; width: calc(100% - 32px); box-shadow: var(--shadow); color: var(--plum); }
.dialog::backdrop { background: rgba(74, 42, 60, .35); backdrop-filter: blur(2px); }
.dialog-body { padding: 22px; display: grid; gap: 10px; }
.pl-entries { list-style: none; margin: 0; padding: 0; max-height: 45vh; overflow: auto; display: grid; gap: 6px; }
.pl-entries li label { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 12px; background: var(--cream); cursor: pointer; }
.pl-entries li input { accent-color: var(--pink-strong); width: 18px; height: 18px; }
.pl-entries .dur { margin-left: auto; color: var(--muted); font-size: .8rem; }
.note { font-size: .88rem; color: var(--muted); background: var(--lilac-soft); border-radius: 12px; padding: 8px 12px; margin: 0; }
.dialog-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.hidden { display: none !important; }

/* toasts */
.toasts { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); display: grid; gap: 8px; z-index: 10; width: min(92vw, 420px); }
.toast { background: var(--plum); color: #fff; padding: 12px 16px; border-radius: 14px; font-weight: 600; box-shadow: 0 10px 30px rgba(0,0,0,.2); animation: rise .25s ease; }
.toast.ok { background: #23795A; }
.toast.error { background: #B3362B; }
@keyframes rise { from { transform: translateY(12px); opacity: 0; } to { transform: none; opacity: 1; } }

/* login */
.login-page { display: grid; place-items: center; padding: 16px; }
.login-card { max-width: 380px; width: 100%; text-align: center; }
.login-form { display: grid; gap: 10px; margin-top: 8px; }

@media (max-width: 560px) {
  .item { grid-template-columns: 72px 1fr; }
  .thumb { width: 72px; height: 54px; }
  .brand-text small { display: none; }
  .card { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  .progress > span, .pill .dot, .toast { animation: none !important; }
}
```

- [ ] **Step 7 : Écrire `app.js`**

`bookmallow/static/app.js` :
```js
/* Bookmallow front-end: one page, no dependencies. */
(() => {
  "use strict";

  const I18N = {
    fr: {
      tagline: "Tes vidéos YouTube en audiobooks",
      hero_title: "Un lien, un audiobook 🎧",
      hero_lead: "Colle un lien YouTube, choisis la qualité, et Bookmallow te prépare un MP3 à écouter partout.",
      url_label: "Lien YouTube",
      convert: "Transformer",
      quality: "Qualité",
      q64: "Voix · 64k", q64_hint: "≈ 29 Mo/heure, idéal pour un livre lu",
      q128: "Équilibré · 128k", q128_hint: "≈ 58 Mo/heure",
      q192: "Musique · 192k", q192_hint: "≈ 86 Mo/heure",
      queue: "File d'attente",
      queue_empty: "Rien en cours. Colle un lien pour commencer ✨",
      library: "Bibliothèque",
      library_empty: "Aucun fichier pour l'instant.",
      banner: "Bookmallow ne garde que les {n} derniers fichiers : pense à télécharger le tien rapidement 💾",
      banner_one: "Bookmallow ne garde qu'un seul fichier : télécharge-le dès qu'il est prêt 💾",
      next_to_go: "prochain à disparaître",
      expired: "Ce fichier a été supprimé pour faire de la place.",
      download: "Télécharger 💾",
      delete: "Supprimer",
      cancel: "Annuler",
      confirm_delete: "Supprimer « {name} » ?",
      logout: "Se déconnecter",
      footer: "fait avec 💗 à la maison",
      status_queued: "En attente",
      status_fetching: "Récupération des infos…",
      status_converting: "Conversion…",
      status_done: "Prêt",
      status_failed: "Échec",
      status_cancelled: "Annulé",
      err_invalid_url: "Bookmallow n'accepte que les liens YouTube.",
      err_bad_quality: "Qualité inconnue.",
      err_duplicate: "Cette vidéo est déjà dans la file.",
      err_network: "Impossible de joindre le serveur.",
      err_playlist: "Impossible de lire cette playlist.",
      added_one: "Ajouté à la file 🎀",
      added_many: "{n} vidéos ajoutées à la file 🎀",
      skipped: "{n} déjà en file",
      pl_title: "Playlist « {title} »",
      pl_intro: "{count} vidéos trouvées. Coche celles que tu veux convertir.",
      pl_note: "Bookmallow ne garde que {max} fichiers : au maximum {max} vidéos seront ajoutées.",
      pl_single: "Seulement cette vidéo",
      pl_add: "Ajouter {n} vidéo(s)",
      e_private: "Vidéo privée",
      e_age: "Réservée aux adultes (connexion requise)",
      e_geo: "Non disponible dans ce pays",
      e_unavailable: "Vidéo indisponible",
      e_live: "Les directs ne sont pas pris en charge",
      e_no_space: "Pas assez d'espace disque",
      e_too_long: "Vidéo trop longue pour ce serveur",
      e_interrupted: "Interrompue par un redémarrage",
      e_timeout: "YouTube n'a pas répondu à temps",
      e_metadata: "Infos de la vidéo illisibles",
      e_ytdlp: "Erreur yt-dlp",
      e_ffmpeg: "Erreur de conversion",
      e_internal: "Erreur interne",
      hours: "h", minutes: "min",
      lang_switch: "English",
    },
    en: {
      tagline: "Your YouTube videos as audiobooks",
      hero_title: "One link, one audiobook 🎧",
      hero_lead: "Paste a YouTube link, pick a quality, and Bookmallow prepares an MP3 you can listen to anywhere.",
      url_label: "YouTube link",
      convert: "Convert",
      quality: "Quality",
      q64: "Voice · 64k", q64_hint: "≈ 29 MB/hour, ideal for narration",
      q128: "Balanced · 128k", q128_hint: "≈ 58 MB/hour",
      q192: "Music · 192k", q192_hint: "≈ 86 MB/hour",
      queue: "Queue",
      queue_empty: "Nothing in progress. Paste a link to begin ✨",
      library: "Library",
      library_empty: "No files yet.",
      banner: "Bookmallow only keeps the {n} most recent files: download yours soon 💾",
      banner_one: "Bookmallow only keeps one file: download it as soon as it is ready 💾",
      next_to_go: "next to go",
      expired: "This file was removed to make room.",
      download: "Download 💾",
      delete: "Delete",
      cancel: "Cancel",
      confirm_delete: "Delete “{name}”?",
      logout: "Log out",
      footer: "made with 💗 at home",
      status_queued: "Queued",
      status_fetching: "Fetching info…",
      status_converting: "Converting…",
      status_done: "Ready",
      status_failed: "Failed",
      status_cancelled: "Cancelled",
      err_invalid_url: "Bookmallow only accepts YouTube links.",
      err_bad_quality: "Unknown quality.",
      err_duplicate: "This video is already queued.",
      err_network: "Cannot reach the server.",
      err_playlist: "Could not read this playlist.",
      added_one: "Added to the queue 🎀",
      added_many: "{n} videos added to the queue 🎀",
      skipped: "{n} already queued",
      pl_title: "Playlist “{title}”",
      pl_intro: "{count} videos found. Tick the ones you want to convert.",
      pl_note: "Bookmallow keeps only {max} files: at most {max} videos will be added.",
      pl_single: "Only this video",
      pl_add: "Add {n} video(s)",
      e_private: "Private video",
      e_age: "Age-restricted (sign-in required)",
      e_geo: "Not available in this country",
      e_unavailable: "Video unavailable",
      e_live: "Live streams are not supported",
      e_no_space: "Not enough disk space",
      e_too_long: "Video too long for this server",
      e_interrupted: "Interrupted by a restart",
      e_timeout: "YouTube did not answer in time",
      e_metadata: "Unreadable video info",
      e_ytdlp: "yt-dlp error",
      e_ffmpeg: "Conversion error",
      e_internal: "Internal error",
      hours: "h", minutes: "min",
      lang_switch: "Français",
    },
  };

  const body = document.body;
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const child of children) if (child) node.append(child);
    return node;
  };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  const state = {
    lang: store.get("bookmallow.lang") || body.dataset.defaultLang || "fr",
    quality: store.get("bookmallow.quality") || body.dataset.defaultQuality || "64",
    maxFiles: Number(body.dataset.maxFiles || 6),
    data: null,
    timer: null,
    pendingPlaylist: null,
  };
  if (!I18N[state.lang]) state.lang = "fr";

  const t = (key, vars = {}) => {
    const text = (I18N[state.lang] && I18N[state.lang][key]) || I18N.fr[key] || key;
    return text.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{${k}}`));
  };

  const fmtDuration = (s) => {
    if (!s && s !== 0) return "";
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h ? `${h} ${t("hours")} ${String(m).padStart(2, "0")}` : `${m} ${t("minutes")}`;
  };
  const fmtSize = (b) => {
    if (!b && b !== 0) return "";
    if (b < 1024 * 1024) return `${Math.round(b / 1024)} ${state.lang === "fr" ? "Ko" : "KB"}`;
    if (b < 1024 * 1024 * 1024) return `${(b / 1048576).toFixed(b < 10 * 1048576 ? 1 : 0)} ${state.lang === "fr" ? "Mo" : "MB"}`;
    return `${(b / 1073741824).toFixed(2)} ${state.lang === "fr" ? "Go" : "GB"}`;
  };
  const fmtDate = (iso) => {
    try { return new Date(iso).toLocaleString(state.lang === "fr" ? "fr-FR" : "en-GB", { dateStyle: "medium", timeStyle: "short" }); }
    catch { return iso; }
  };

  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    $("#lang-toggle").textContent = t("lang_switch");
    renderQualities();
    if (state.data) render(state.data);
  }

  function renderQualities() {
    const box = $("#qualities");
    box.querySelectorAll(".quality").forEach((n) => n.remove());
    for (const q of ["64", "128", "192"]) {
      const id = `q-${q}`;
      const input = el("input", { type: "radio", name: "quality", id, value: q, onchange: () => { state.quality = q; store.set("bookmallow.quality", q); } });
      if (q === state.quality) input.checked = true;
      box.append(el("div", { class: "quality" }, [input, el("label", { for: id }, [el("b", { text: t(`q${q}`) }), el("small", { text: t(`q${q}_hint`) })])]));
    }
  }

  function toast(text, kind = "") {
    const node = el("div", { class: `toast ${kind}`, text });
    $("#toasts").append(node);
    setTimeout(() => node.remove(), 4200);
  }

  function setMsg(text, kind = "") {
    const node = $("#form-msg");
    node.textContent = text;
    node.className = `form-msg ${kind}`;
  }

  async function api(path, options = {}) {
    let res;
    try {
      res = await fetch(path, { headers: { "Content-Type": "application/json", Accept: "application/json" }, credentials: "same-origin", ...options });
    } catch {
      throw { network: true };
    }
    if (res.status === 401) { window.location.href = "/login?next=/"; throw { unauthorized: true }; }
    const payload = res.status === 204 ? null : await res.json().catch(() => ({}));
    return { status: res.status, ok: res.ok, payload };
  }

  // ---- rendering ---------------------------------------------------------------------

  function thumb(url) {
    const box = el("div", { class: "thumb" });
    if (url) box.append(el("img", { src: url, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }));
    else box.textContent = "🎧";
    return box;
  }

  function statusPill(status) {
    return el("span", { class: `pill ${status}` }, [el("span", { class: "dot" }), document.createTextNode(t(`status_${status}`))]);
  }

  function jobCard(job) {
    const meta = [];
    if (job.channel) meta.push(el("span", { text: job.channel }));
    if (job.duration) meta.push(el("span", { text: fmtDuration(job.duration) }));
    meta.push(el("span", { text: t(`q${job.quality}`) }));
    const bodyParts = [
      el("div", { class: "item-title", text: job.title || job.url }),
      el("div", { class: "item-meta" }, meta),
      el("div", { class: "item-actions" }, [statusPill(job.status)]),
    ];
    if (job.status === "converting") {
      const bar = el("div", { class: `progress${job.progress > 0 ? "" : " indeterminate"}` }, [el("span")]);
      if (job.progress > 0) bar.firstChild.style.width = `${job.progress}%`;
      bodyParts.push(bar);
      if (job.progress > 0) bodyParts.push(el("div", { class: "progress-label", text: `${job.progress.toFixed(1)} %` }));
    } else if (job.status === "fetching" || job.status === "queued") {
      bodyParts.push(el("div", { class: "progress indeterminate" }, [el("span")]));
    }
    if (job.status === "failed") {
      const err = el("div", { class: "item-error", text: t(`e_${job.error_code || "internal"}`) });
      if (job.error) err.append(el("small", { text: job.error }));
      bodyParts.push(err);
    }
    if (job.status === "done") {
      if (job.expired) bodyParts.push(el("div", { class: "muted", text: t("expired") }));
      else bodyParts[2].append(el("a", { class: "btn primary small", href: `/api/files/${encodeURIComponent(job.filename)}`, text: t("download") }));
    }
    if (["queued", "fetching", "converting"].includes(job.status)) {
      bodyParts[2].append(el("button", { class: "btn ghost small", type: "button", text: t("cancel"), onclick: () => cancelJob(job.id) }));
    }
    return el("li", { class: `item${job.expired ? " expired" : ""}`, "data-id": job.id }, [thumb(job.thumbnail), el("div", { class: "item-body" }, bodyParts)]);
  }

  function fileCard(file, nextToGo) {
    const meta = [];
    if (file.channel) meta.push(el("span", { text: file.channel }));
    if (file.duration) meta.push(el("span", { text: fmtDuration(file.duration) }));
    meta.push(el("span", { text: fmtSize(file.size_bytes) }));
    if (file.quality) meta.push(el("span", { text: t(`q${file.quality}`) }));
    meta.push(el("span", { text: fmtDate(file.modified_at) }));
    const actions = el("div", { class: "item-actions" }, [
      el("a", { class: "btn primary small", href: `/api/files/${encodeURIComponent(file.name)}`, text: t("download") }),
      el("button", { class: "btn ghost small danger", type: "button", text: t("delete"), onclick: () => deleteFile(file) }),
    ]);
    if (file.name === nextToGo) actions.append(el("span", { class: "badge", text: `⏳ ${t("next_to_go")}` }));
    return el("li", { class: "item" }, [thumb(file.thumbnail), el("div", { class: "item-body" }, [
      el("div", { class: "item-title", text: file.title }), el("div", { class: "item-meta" }, meta), actions])]);
  }

  function render(data) {
    state.data = data;
    const maxFiles = data.retention.max_files;
    $("#banner").textContent = maxFiles === 1 ? t("banner_one") : t("banner", { n: maxFiles });

    const visibleJobs = data.jobs
      .filter((j) => j.status !== "done" || j.expired)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    const jobsList = $("#jobs");
    jobsList.replaceChildren(...visibleJobs.map(jobCard));
    $("#jobs-empty").classList.toggle("hidden", visibleJobs.length > 0);
    const active = data.jobs.filter((j) => ["queued", "fetching", "converting"].includes(j.status)).length;
    $("#queue-count").textContent = active ? String(active) : "";

    const filesList = $("#files");
    filesList.replaceChildren(...data.files.map((f) => fileCard(f, data.retention.next_to_go)));
    $("#files-empty").classList.toggle("hidden", data.files.length > 0);
    $("#files-count").textContent = data.files.length ? `${data.files.length}/${maxFiles}` : "";

    schedule(active > 0 ? 2000 : 10000);
  }

  function schedule(ms) {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, ms);
  }

  async function refresh() {
    try {
      const { ok, payload } = await api("/api/state");
      if (ok) render(payload); else schedule(5000);
    } catch (err) {
      if (!err.unauthorized) schedule(5000);
    }
  }

  // ---- actions -----------------------------------------------------------------------

  async function submit(extra = {}) {
    const url = $("#url").value.trim();
    if (!url) return;
    const btn = $("#submit-btn");
    btn.disabled = true;
    setMsg("");
    try {
      const { status, payload } = await api("/api/jobs", { method: "POST", body: JSON.stringify({ url, quality: state.quality, ...extra }) });
      if (status === 201) {
        const n = payload.jobs.length;
        toast(n === 1 ? t("added_one") : t("added_many", { n }), "ok");
        if (payload.skipped && payload.skipped.length) setMsg(t("skipped", { n: payload.skipped.length }));
        $("#url").value = "";
        closePlaylist();
        refresh();
      } else if (status === 200 && payload.playlist) {
        openPlaylist(payload.playlist);
      } else if (status === 409) {
        setMsg(t("err_duplicate"), "error");
      } else if (status === 400) {
        setMsg(t(payload.error === "bad_quality" ? "err_bad_quality" : "err_invalid_url"), "error");
      } else if (status === 502) {
        setMsg(`${t("err_playlist")} ${payload.code ? t(`e_${payload.code}`) : ""}`.trim(), "error");
      } else {
        setMsg(t("e_internal"), "error");
      }
    } catch (err) {
      if (err.network) setMsg(t("err_network"), "error");
    } finally {
      btn.disabled = false;
    }
  }

  async function cancelJob(id) {
    try { await api(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }); refresh(); }
    catch (err) { if (err.network) toast(t("err_network"), "error"); }
  }

  async function deleteFile(file) {
    if (!window.confirm(t("confirm_delete", { name: file.title }))) return;
    try { await api(`/api/files/${encodeURIComponent(file.name)}`, { method: "DELETE" }); refresh(); }
    catch (err) { if (err.network) toast(t("err_network"), "error"); }
  }

  // ---- playlist dialog ---------------------------------------------------------------

  function openPlaylist(pl) {
    state.pendingPlaylist = pl;
    $("#pl-title").textContent = t("pl_title", { title: pl.title });
    $("#pl-intro").textContent = t("pl_intro", { count: pl.count });
    $("#pl-note").textContent = t("pl_note", { max: pl.max_files });
    const list = $("#pl-entries");
    list.replaceChildren(...pl.entries.map((e, i) => {
      const id = `pl-${e.video_id}`;
      const input = el("input", { type: "checkbox", id, value: e.video_id, onchange: updatePlaylistButton });
      input.checked = i < pl.max_files;
      return el("li", {}, [el("label", { for: id }, [input, el("span", { text: e.title }), el("span", { class: "dur", text: fmtDuration(e.duration) })])]);
    }));
    $("#pl-single").classList.toggle("hidden", !pl.single_video_url);
    updatePlaylistButton();
    const dialog = $("#playlist-dialog");
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
  }

  function selectedPlaylistIds() {
    return [...document.querySelectorAll("#pl-entries input:checked")].map((i) => i.value);
  }

  function updatePlaylistButton() {
    const max = state.pendingPlaylist ? state.pendingPlaylist.max_files : state.maxFiles;
    const n = Math.min(selectedPlaylistIds().length, max);
    const btn = $("#pl-add");
    btn.textContent = t("pl_add", { n });
    btn.disabled = n === 0;
  }

  function closePlaylist() {
    const dialog = $("#playlist-dialog");
    if (dialog.open) dialog.close();
    state.pendingPlaylist = null;
  }

  // ---- wiring ------------------------------------------------------------------------

  $("#submit-form").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  $("#url").addEventListener("paste", () => setTimeout(() => { if ($("#url").value.trim()) submit(); }, 50));
  $("#lang-toggle").addEventListener("click", () => {
    state.lang = state.lang === "fr" ? "en" : "fr";
    store.set("bookmallow.lang", state.lang);
    applyI18n();
  });
  $("#pl-cancel").addEventListener("click", closePlaylist);
  $("#pl-single").addEventListener("click", () => submit({ playlist: "ignore" }));
  $("#pl-add").addEventListener("click", () => submit({ playlist: "expand", video_ids: selectedPlaylistIds() }));
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });

  applyI18n();
  refresh();
})();
```

- [ ] **Step 8 : Vérifier** — `.venv/bin/pytest tests/test_frontend.py tests/test_app.py` → tous `passed`.

- [ ] **Step 9 : Vérification visuelle**

```bash
cd /home/clem/bookmallow && DATA_DIR=./data APP_PASSWORD= .venv/bin/flask --app wsgi:app run --port 7843 --host 127.0.0.1 &
sleep 2 && curl -s http://127.0.0.1:7843/api/state | head -c 300; echo
```
Ouvrir `http://<ip-du-pi>:7843` (ou via tunnel SSH) : la page pastel s'affiche, les trois pastilles de qualité, la bascule FR/EN fonctionne, le bandeau rétention mentionne 6 fichiers. Coller un lien non YouTube → message rouge « Bookmallow n'accepte que les liens YouTube ». Arrêter le serveur (`kill %1`) et supprimer `./data`.

- [ ] **Step 10 : Commit**

```bash
git add bookmallow/templates bookmallow/static tests/test_frontend.py && git commit -m "feat: pastel single-page UI with FR/EN, queue, library and playlist dialog"
```

---

### Task 12 : Image Docker, entrypoint, compose et test de bout en bout

**Files:**
- Modify: `Dockerfile`, `docker-compose.yml`
- Create: `entrypoint.sh`, `.dockerignore`

**Interfaces:**
- Consumes: `wsgi:app` (T10), `requirements*.txt`, `tests/` (T1–T11).
- Produces : image en trois étapes `base` → `test` (lance pytest) → `runtime` (gunicorn, utilisateur `bookmallow` ajusté à `PUID/PGID`, healthcheck `/healthz`). Variable supplémentaire `YTDLP_AUTO_UPDATE=1` (optionnelle) pour mettre yt-dlp à jour au démarrage.

- [ ] **Step 1 : Écrire le `Dockerfile`** (remplacer entièrement)

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ARG TARGETARCH
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg converts, gosu drops privileges, deno is the JavaScript runtime yt-dlp needs for YouTube.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg gosu ca-certificates curl unzip; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64) DENO_ARCH=x86_64 ;; \
      arm64) DENO_ARCH=aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/deno.zip "https://github.com/denoland/deno/releases/latest/download/deno-${DENO_ARCH}-unknown-linux-gnu.zip"; \
    unzip -q /tmp/deno.zip -d /usr/local/bin; \
    rm /tmp/deno.zip; \
    chmod +x /usr/local/bin/deno; \
    apt-get purge -y curl unzip; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*; \
    deno --version; \
    ffmpeg -version | head -n 1

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY bookmallow ./bookmallow
COPY wsgi.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh \
 && useradd --system --uid 1000 --create-home --shell /usr/sbin/nologin bookmallow

# ---- test stage: `docker build --target test .` runs the suite inside the real image ----
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
COPY tests ./tests
RUN pip install -r requirements-dev.txt && pytest

# ---- runtime ------------------------------------------------------------------------------
FROM base AS runtime
ENV DATA_DIR=/data \
    PUID=1000 \
    PGID=1000
VOLUME ["/data"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3).status == 200 else 1)"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "300", "--access-logfile", "-", "wsgi:app"]
```

- [ ] **Step 2 : Écrire `entrypoint.sh`**

```sh
#!/bin/sh
# Align the bookmallow user with PUID/PGID so files in /data belong to the host user, then drop root.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
  groupmod -o -g "$PGID" bookmallow
  usermod -o -u "$PUID" -g "$PGID" bookmallow
  mkdir -p "$DATA_DIR"
  chown -R bookmallow:bookmallow "$DATA_DIR" /home/bookmallow
  if [ "${YTDLP_AUTO_UPDATE:-0}" = "1" ]; then
    echo "[bookmallow] updating yt-dlp..."
    pip install -q --upgrade "yt-dlp[default]" || echo "[bookmallow] yt-dlp update failed, keeping the bundled version"
  fi
  echo "[bookmallow] yt-dlp $(yt-dlp --version) | $(ffmpeg -version | head -n 1 | cut -d' ' -f1-3) | uid=$PUID gid=$PGID | data=$DATA_DIR"
  exec gosu bookmallow "$@"
fi
exec "$@"
```

- [ ] **Step 3 : Écrire `.dockerignore` et le `docker-compose.yml` d'exemple**

`.dockerignore` :
```
.git
.venv
data
docs
.github
.pytest_cache
**/__pycache__
*.md
```

`docker-compose.yml` (remplacer entièrement) :
```yaml
# Bookmallow — YouTube → audiobook MP3, self-hosted.
# Image publique multi-arch (amd64, arm64). Décommente `build: .` pour construire toi-même.
services:
  bookmallow:
    image: ghcr.io/clemdepernet/bookmallow:latest
    # build: .
    container_name: bookmallow
    ports:
      - "7843:5000"
    volumes:
      - ./data:/data
    environment:
      - TZ=Europe/Paris
      - PUID=1000
      - PGID=1000
      - MAX_FILES=6            # nombre de MP3 conservés / MP3s kept
      - DEFAULT_QUALITY=64     # 64 (voix, mono) | 128 | 192
      - DEFAULT_LANG=fr        # fr | en
      # - APP_PASSWORD=change-me   # mot de passe partagé, vide = désactivé / shared password, empty = off
      # - MIN_FREE_MB=500          # marge d'espace disque à garder / free space to keep
      # - MAX_DURATION_HOURS=0     # 0 = pas de limite / no limit
      # - YTDLP_AUTO_UPDATE=1      # met yt-dlp à jour au démarrage / update yt-dlp at start
      # - FORCE_HTTPS=1            # cookie Secure derrière un reverse proxy HTTPS
    restart: unless-stopped
```

- [ ] **Step 4 : Construire l'étape de test puis l'image finale sur le Pi**

```bash
cd /home/clem/bookmallow && docker build --target test -t bookmallow:test . 2>&1 | tail -20
```
Attendu : la suite pytest passe dans l'image (ligne `passed`). Si le téléchargement de deno échoue (réseau), relancer ; si `useradd` se plaint que l'UID 1000 existe, passer à `--uid 1500` dans le Dockerfile (l'entrypoint le réaligne de toute façon).

```bash
docker build --target runtime -t bookmallow:dev . 2>&1 | tail -5 && docker image ls bookmallow:dev
```

- [ ] **Step 5 : Test de bout en bout avec une vraie vidéo courte**

```bash
mkdir -p $SCRATCH/bm-data
docker run -d --rm --name bm-e2e -p 7843:5000 -e MAX_FILES=2 -e TZ=Asia/Kuala_Lumpur \
  -v $SCRATCH/bm-data:/data bookmallow:dev
sleep 6 && docker logs bm-e2e | tail -5
curl -s -X POST http://127.0.0.1:7843/api/jobs -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw","quality":"64"}'
```
Attendu : `201` avec un job `queued`. Puis, pendant 30 s :
```bash
for i in $(seq 1 15); do curl -s http://127.0.0.1:7843/api/state | python3 -c 'import json,sys; d=json.load(sys.stdin); j=d["jobs"][-1]; print(j["status"], j["progress"], j.get("error_code"), j.get("filename"))'; ls $SCRATCH/bm-data; sleep 2; done
```
Vérifications :
- pendant la conversion, seul un fichier `*.part.mp3` apparaît dans le volume (jamais de `.webm`/`.m4a`) ;
- fin : `done`, un `Me at the zoo [jNQXAC9IVRw].mp3` d'environ 150 Ko (19 s à 64 kbps) ;
- `ffprobe` (via l'image) confirme mono 64 kbps et le tag titre :
```bash
docker exec bm-e2e ffprobe -v error -show_entries stream=channels,bit_rate:format_tags=title,artist -of default=nw=1 "/data/Me at the zoo [jNQXAC9IVRw].mp3"
```
- téléchargement : `curl -sI "http://127.0.0.1:7843/api/files/Me%20at%20the%20zoo%20%5BjNQXAC9IVRw%5D.mp3" | grep -i 'content-disposition\|accept-ranges'` → `attachment` et `bytes` ;
- propriétaire des fichiers sur l'hôte = `clem` (uid 1000) : `ls -ln .../bm-data` ;
- rétention : soumettre deux autres vidéos courtes (`https://www.youtube.com/watch?v=aqz-KE-bpKQ` et `https://www.youtube.com/watch?v=hY7m5jjJ9mM`) ; à la fin il ne reste que 2 MP3 et `/api/state` renvoie `next_to_go` non nul ;
- erreur lisible : soumettre `https://www.youtube.com/watch?v=aaaaaaaaaaa` → job `failed` avec `error_code` `unavailable` ;
- redémarrage : `docker restart bm-e2e` pendant une conversion → au retour le job est `failed`/`interrupted` et aucun `.part.mp3` ne traîne.

Si yt-dlp échoue avec un message parlant de « JavaScript runtime » ou « n challenge », vérifier `docker exec bm-e2e deno --version` et `docker exec bm-e2e yt-dlp --version` ; mettre à jour via `YTDLP_AUTO_UPDATE=1` pour tester.

Nettoyage : `docker rm -f bm-e2e && rm -rf .../bm-data`.

- [ ] **Step 6 : Commit**

```bash
git add Dockerfile entrypoint.sh .dockerignore docker-compose.yml && git commit -m "build: slim multi-stage image with ffmpeg, deno, PUID/PGID entrypoint and healthcheck"
```

---

### Task 13 : CI, README bilingue, licence, changelog, post Reddit

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/dependabot.yml`, `CHANGELOG.md`, `docs/reddit-post.md`, `docs/screenshot.png`
- Modify: `README.md`, `LICENSE`, `CONTRIBUTING.md`

- [ ] **Step 1 : Workflows GitHub Actions**

`.github/workflows/ci.yml` :
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: pytest
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Build test stage
        uses: docker/build-push-action@v6
        with:
          context: .
          target: test
          push: false
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

`.github/workflows/release.yml` :
```yaml
name: Release image
on:
  push:
    tags: ["v*"]
  schedule:
    - cron: "17 4 * * 1"   # Mondays: rebuild so the image ships a fresh yt-dlp
  workflow_dispatch:
permissions:
  contents: read
  packages: write
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest
      - uses: docker/build-push-action@v6
        with:
          context: .
          target: runtime
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

`.github/dependabot.yml` :
```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule: { interval: weekly }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: /
    schedule: { interval: weekly }
```

- [ ] **Step 2 : `LICENSE`** — garder le texte MIT, remplacer la ligne de copyright par les deux lignes :
```
Copyright (c) 2026 clemdepernet (Bookmallow)
Copyright (c) 2024 YouTube to MP3 Downloader (original project by TheFatPanda-Dev)
```

- [ ] **Step 3 : `CHANGELOG.md`**

```markdown
# Changelog

## 1.0.0 — 2026-09-23

First Bookmallow release, forked from TheFatPanda-Dev/youtube-to-mp3-docker.

- Streaming conversion (`yt-dlp -o - | ffmpeg`): only the final MP3 ever touches the disk.
- Single-worker queue with live progress, cancel, and recovery after a restart.
- Retention: keep the newest `MAX_FILES` (default 6), the UI warns and marks the next file to go.
- Audiobook-friendly default: 64 kbps mono (≈ 29 MB/hour), 128/192 kbps available.
- Optional shared password (`APP_PASSWORD`).
- Pastel FR/EN single-page UI, no external resources.
- Slim multi-arch image (amd64/arm64) with ffmpeg and deno, `PUID/PGID`, healthcheck.
```

- [ ] **Step 4 : `CONTRIBUTING.md`** (remplacer)

```markdown
# Contributing

Merci ! / Thanks!

- Run the tests: `python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest`
- Run the app locally: `DATA_DIR=./data .venv/bin/flask --app wsgi:app run --port 7843` (needs `yt-dlp`, `ffmpeg` and `deno` on your PATH for real conversions)
- Build the image with its tests: `docker build --target test .`
- Keep modules small and tested; the external tools (`yt-dlp`, `ffmpeg`) are always injected in tests, never executed.
- UI strings live in `bookmallow/static/app.js` (`I18N`), keep `fr` and `en` in sync.
```

- [ ] **Step 5 : `README.md`** (remplacer entièrement)

```markdown
<p align="center"><img src="bookmallow/static/logo.svg" width="96" alt=""></p>
<h1 align="center">Bookmallow</h1>
<p align="center">Tes vidéos YouTube en audiobooks MP3, en douceur. · Your YouTube videos as audiobook MP3s, gently.</p>
<p align="center"><img src="docs/screenshot.png" width="720" alt="Bookmallow screenshot"></p>

---

## 🇫🇷 Français

Bookmallow est un petit conteneur auto-hébergé : tu colles un lien YouTube, il te rend un MP3 « audiobook », depuis une interface pastel accessible depuis ton téléphone. Il est conçu pour un Raspberry Pi et pour les vidéos **très** longues (10 h, 17 h…) : l'audio est converti **en streaming**, sans jamais stocker la vidéo ni l'audio brut sur le disque.

### Pourquoi

- **Zéro fichier intermédiaire** : `yt-dlp` envoie l'audio directement à `ffmpeg`. Une vidéo de 10 h pèse ~290 Mo en 64 kbps mono, au lieu de 1,5 Go de pic avec un téléchargement classique.
- **File d'attente** : une conversion à la fois, progression en direct, annulation, reprise après redémarrage.
- **Rétention** : Bookmallow ne garde que les `MAX_FILES` derniers fichiers (6 par défaut). L'interface le rappelle et marque le prochain fichier qui disparaîtra.
- **Pour partager** : mot de passe optionnel, interface FR/EN, aucune ressource externe.

### Démarrer en 3 commandes

```bash
mkdir bookmallow && cd bookmallow
curl -fsSLO https://raw.githubusercontent.com/clemdepernet/bookmallow/main/docker-compose.yml
docker compose up -d
```

Ouvre `http://<ton-serveur>:7843`. Les MP3 arrivent dans `./data`.

### Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `MAX_FILES` | `6` | Nombre de MP3 conservés ; les plus anciens sont supprimés |
| `DEFAULT_QUALITY` | `64` | `64` (voix, mono, ~29 Mo/h), `128` (~58 Mo/h) ou `192` (~86 Mo/h) |
| `APP_PASSWORD` | vide | Mot de passe partagé ; vide = pas de connexion |
| `DEFAULT_LANG` | `fr` | `fr` ou `en` (chaque personne peut basculer) |
| `MIN_FREE_MB` | `500` | Espace disque à toujours garder libre |
| `MAX_DURATION_HOURS` | `0` | `0` = aucune limite de durée |
| `PUID` / `PGID` | `1000` | Propriétaire des fichiers dans `./data` |
| `TZ` | `UTC` | Fuseau horaire des logs |
| `YTDLP_AUTO_UPDATE` | `0` | `1` = met yt-dlp à jour à chaque démarrage |
| `FORCE_HTTPS` | `0` | `1` derrière un reverse proxy HTTPS (cookie `Secure`) |
| `SECRET_KEY` | générée | Clé des sessions, persistée dans `/data/.secret` |

### Partager avec ses amies

Mets un `APP_PASSWORD`, puis expose le port 7843 avec ton reverse proxy habituel (Nginx Proxy Manager, Caddy, Traefik) ou un tunnel Cloudflare. Bookmallow n'accepte que des liens YouTube et ne convertit qu'une vidéo à la fois : même partagé, il reste sage avec ton Pi.

### YouTube change souvent

`yt-dlp` doit suivre YouTube de près. L'image est reconstruite **chaque lundi** avec la dernière version : un `docker compose pull && docker compose up -d` suffit. En dépannage rapide, `YTDLP_AUTO_UPDATE=1` met yt-dlp à jour au démarrage du conteneur.

### Construire soi-même

```bash
git clone https://github.com/clemdepernet/bookmallow.git && cd bookmallow
docker build --target test .        # lance la suite de tests dans l'image
docker compose up -d --build        # après avoir décommenté `build: .`
```

---

## 🇬🇧 English

Bookmallow is a tiny self-hosted container: paste a YouTube link, get an audiobook-style MP3 from a pastel web UI that works on your phone. It is built for a Raspberry Pi and for **very** long videos (10 h, 17 h…): audio is converted **while streaming**, the video or raw audio is never written to disk.

### Why

- **No intermediate file**: `yt-dlp` pipes audio straight into `ffmpeg`. A 10-hour video is ~290 MB at 64 kbps mono instead of a 1.5 GB peak with a classic download-then-convert.
- **Queue**: one conversion at a time, live progress, cancel, recovery after a restart.
- **Retention**: only the newest `MAX_FILES` files are kept (6 by default). The UI says so and marks the next file to go.
- **Made to share**: optional password, FR/EN interface, no external resources.

### Quick start

```bash
mkdir bookmallow && cd bookmallow
curl -fsSLO https://raw.githubusercontent.com/clemdepernet/bookmallow/main/docker-compose.yml
docker compose up -d
```

Open `http://<your-server>:7843`. MP3s land in `./data`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MAX_FILES` | `6` | MP3s kept; older ones are deleted |
| `DEFAULT_QUALITY` | `64` | `64` (voice, mono, ~29 MB/h), `128` (~58 MB/h) or `192` (~86 MB/h) |
| `APP_PASSWORD` | empty | Shared password; empty = no login |
| `DEFAULT_LANG` | `fr` | `fr` or `en` (each visitor can switch) |
| `MIN_FREE_MB` | `500` | Disk space to always keep free |
| `MAX_DURATION_HOURS` | `0` | `0` = no duration limit |
| `PUID` / `PGID` | `1000` | Owner of the files in `./data` |
| `TZ` | `UTC` | Log timezone |
| `YTDLP_AUTO_UPDATE` | `0` | `1` = upgrade yt-dlp at every start |
| `FORCE_HTTPS` | `0` | `1` behind an HTTPS reverse proxy (`Secure` cookie) |
| `SECRET_KEY` | generated | Session key, persisted in `/data/.secret` |

### Sharing with friends

Set `APP_PASSWORD`, then expose port 7843 through your usual reverse proxy (Nginx Proxy Manager, Caddy, Traefik) or a Cloudflare tunnel. Bookmallow only accepts YouTube links and converts one video at a time, so it stays gentle with your Pi even when shared.

### YouTube changes often

`yt-dlp` has to keep up with YouTube. The image is rebuilt **every Monday** with the latest release: `docker compose pull && docker compose up -d` is all you need. As a quick fix, `YTDLP_AUTO_UPDATE=1` upgrades yt-dlp when the container starts.

### Build it yourself

```bash
git clone https://github.com/clemdepernet/bookmallow.git && cd bookmallow
docker build --target test .        # runs the test suite inside the image
docker compose up -d --build        # after uncommenting `build: .`
```

---

## Credits

Bookmallow started as a fork of [TheFatPanda-Dev/youtube-to-mp3-docker](https://github.com/TheFatPanda-Dev/youtube-to-mp3-docker) (MIT). Thank you! The backend was rewritten around streaming conversion, a queue and retention; the pastel UI is new.

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org), [Flask](https://flask.palletsprojects.com) and [deno](https://deno.com). MIT license.
```

- [ ] **Step 6 : `docs/reddit-post.md`**

```markdown
# Post r/selfhosted (brouillon)

**Titre :** Bookmallow – a tiny pastel self-hosted YouTube → audiobook MP3 converter that streams 10-hour videos without filling your Pi's disk

**Corps :**

Hi! I run a small media stack on a Raspberry Pi 5 and wanted a friendly way to turn long YouTube audiobooks (8–17 hours) into MP3s without the usual "download 1.5 GB of video, then convert" dance that kept filling my disk.

So I forked an existing Flask project and rewrote it into **Bookmallow**:

- **Streams the conversion**: `yt-dlp -o - | ffmpeg`, only the final MP3 touches the disk. A 10 h video is ~290 MB at 64 kbps mono.
- **Queue** with live progress, cancel, and recovery after a restart.
- **Retention**: keeps only the newest N files (default 6) and tells users in the UI which file goes next, so the Pi never fills up.
- **Optional shared password**, FR/EN UI, no CDN/external resources.
- **Multi-arch image** (amd64/arm64), rebuilt weekly so yt-dlp stays fresh. `PUID/PGID`, healthcheck, one volume.
- Yes, it's pink. My partner asked for "girly" and I delivered. 🎀

Repo: https://github.com/clemdepernet/bookmallow
Compose: one file, `docker compose up -d`, open port 7843.

MIT, feedback and PRs welcome. Things I'd love opinions on: chapter-based splitting, and whether per-user libraries are worth the complexity.
```

- [ ] **Step 7 : Capture d'écran**

Lancer l'app (voir Task 11 Step 9) avec un ou deux fichiers factices dans `./data` et un job en cours si possible, puis capturer la page en 1280 px de large et enregistrer `docs/screenshot.png` (via le navigateur ou `chromium --headless --screenshot=docs/screenshot.png --window-size=1280,1400 http://127.0.0.1:7843` si chromium est installé). Le fichier doit peser moins de 600 Ko.

- [ ] **Step 8 : Vérifier**

```bash
.venv/bin/pytest && python3 -c "import yaml" 2>/dev/null || true
docker run --rm -v "$PWD":/w -w /w python:3.12-slim python -c "import json,sys,pathlib; [print(p) for p in pathlib.Path('.github').rglob('*.yml')]"
```
Vérifier à l'œil que les YAML sont bien indentés (ou `docker compose config -q` pour le compose).

- [ ] **Step 9 : Commit**

```bash
git add .github CHANGELOG.md CONTRIBUTING.md LICENSE README.md docs/reddit-post.md docs/screenshot.png && git commit -m "docs: bilingual README, CI and release workflows, changelog, Reddit draft"
```

---

### Task 14 : Publication GitHub et déploiement chez Clem

**Files:**
- Create: `/home/clem/bookmallow-stack/docker-compose.yml`, `/home/clem/bookmallow-stack/.env`
- Modify: `/home/clem/stacks.sh`

- [ ] **Step 1 : Créer le dépôt public et pousser**

```bash
cd /home/clem/bookmallow && gh auth status 2>&1 | grep -i scopes || true
gh repo create clemdepernet/bookmallow --public --source . --remote origin --push \
  --description "Turn YouTube videos into audiobook MP3s, gently. Self-hosted, pastel, streams 10h+ videos without filling the disk."
```
Si le push refuse `.github/workflows` (scope `workflow` manquant sur le token gh), demander à Clem de lancer `gh auth refresh -h github.com -s workflow` dans un terminal interactif, puis `git push -u origin main`.

- [ ] **Step 2 : Ajouter les sujets et vérifier la CI**

```bash
gh repo edit clemdepernet/bookmallow --add-topic youtube --add-topic audiobook --add-topic mp3 --add-topic docker --add-topic self-hosted --add-topic yt-dlp --add-topic raspberry-pi --add-topic flask
sleep 60 && gh run list --repo clemdepernet/bookmallow --limit 3
```
Attendu : workflow `CI` vert (jobs `tests` et `image`).

- [ ] **Step 3 : Tag v1.0.0 et image ghcr.io**

```bash
git tag -a v1.0.0 -m "Bookmallow 1.0.0" && git push origin v1.0.0
gh run watch --repo clemdepernet/bookmallow --exit-status $(gh run list --repo clemdepernet/bookmallow --workflow "Release image" --limit 1 --json databaseId -q '.[0].databaseId')
```
Le paquet `ghcr.io/clemdepernet/bookmallow` est créé **privé** par défaut : Clem doit le passer en public une fois dans GitHub → Packages → bookmallow → Package settings → Change visibility → Public. Tant que ce n'est pas fait, le compose public échoue au `pull` ; le déploiement local ci-dessous construit l'image sur place et ne dépend pas de ça.

- [ ] **Step 4 : Stack locale sur le Pi**

`/home/clem/bookmallow-stack/docker-compose.yml` :
```yaml
services:
  bookmallow:
    image: ghcr.io/clemdepernet/bookmallow:latest
    build: /home/clem/bookmallow
    container_name: bookmallow
    ports:
      - "7843:5000"
    volumes:
      - ./data:/data
    environment:
      - TZ=Asia/Kuala_Lumpur
      - PUID=1000
      - PGID=1000
      - MAX_FILES=6
      - DEFAULT_QUALITY=64
      - DEFAULT_LANG=fr
      - APP_PASSWORD=${APP_PASSWORD}
    restart: unless-stopped
```

`/home/clem/bookmallow-stack/.env` (mode 600) :
```bash
cd /home/clem/bookmallow-stack && printf 'APP_PASSWORD=%s\n' "$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)" > .env && chmod 600 .env && cat .env
```
Noter le mot de passe pour le donner à Clem (elle pourra le changer dans `.env` puis `docker compose up -d`).

```bash
docker compose up -d --build && sleep 20 && docker compose ps && curl -s http://127.0.0.1:7843/healthz
```

- [ ] **Step 5 : Ajouter la stack à `stacks.sh`**

Dans `/home/clem/stacks.sh`, ajouter `"$HOME/bookmallow-stack"` au tableau `STACKS` et remplacer la ligne `update)  docker compose -f "$dir/docker-compose.yml" pull` par `update)  docker compose -f "$dir/docker-compose.yml" pull --ignore-buildable` (les services avec `build:` ne sont pas tirés). Vérifier : `./stacks.sh ps` liste les trois stacks.

- [ ] **Step 6 : Vérification finale et mémoire**

- Ouvrir `http://<ip-du-pi>:7843`, se connecter avec le mot de passe, convertir une vidéo courte de bout en bout depuis l'interface, la télécharger, la supprimer.
- Écrire la mémoire projet (`/home/clem/./projects/-home-clem/memory/`) : Bookmallow vit dans `~/bookmallow` (code) et `~/bookmallow-stack` (déploiement, port 7843), package ghcr à passer public, post Reddit dans `docs/reddit-post.md`.

---

## Self-review (fait à l'écriture du plan)

**Couverture de la spec** : §3 architecture → T10/T12 ; §4 modules → T2–T10 ; §5 modèle → T5 ; §6.1 soumission/playlist → T10 ; §6.2 worker → T9 ; §6.3 streaming → T8 ; §6.4 garde-fou disque → T9 ; §6.5 rétention + UI → T6/T9/T11 ; §6.6 téléchargement Range → T10 ; §6.7 annulation → T8/T9/T10 ; §6.8 démarrage → T9 ; §7 API → T10 ; §8 auth → T10 ; §9 config → T2/T12 ; §10 interface → T11 ; §11 erreurs → T7/T8/T9/T11 ; §12 tests → chaque tâche + étape `test` du Dockerfile ; §13 packaging/publication → T12/T13/T14 ; §14 déploiement → T14. Chapitres ID3 : T8 via ffmetadata (`-map_chapters`), best effort comme prévu par la spec.

**Cohérence des noms** : `JobQueue.process_next/submit/cancel/get/snapshot/recover/start` utilisés à l'identique en T9/T10 ; `resolve_file`, `build_state`, `create_app(config, jobqueue, start_worker, fetch_playlist)` identiques en T10/T11 ; codes d'erreur (`private, age, geo, unavailable, live, timeout, metadata, ytdlp, ffmpeg, no_space, too_long, interrupted, internal`) identiques entre T7/T8/T9 et le dictionnaire `e_*` de T11 ; champ `expired` ajouté par `build_state` et lu par `jobCard`.

**Point d'attention à l'exécution** : `test_cancel_kills_real_processes` (T8) et `test_start_runs_worker_thread` (T9) utilisent de vrais threads/processus ; s'ils sont instables sur le Pi, augmenter les délais plutôt que de les supprimer.
