# Bookmallow Store (v1.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter à Bookmallow un onglet « Magasin » qui cherche des livres audio (LibriVox, Internet Archive, Prowlarr), les acquiert (HTTP direct ou qBittorrent), les assemble en un seul M4B chapitré et les dépose dans la bibliothèque existante soumise à la même rétention.

**Architecture:** Un package `bookmallow/store/` (modèles, HTTP, fournisseurs, recherche unifiée avec cache, assembleur ffmpeg, acquisition torrent) branché sur la `JobQueue` existante via un nouveau `job.kind == "book"`. La rétention, l'état, l'authentification et l'interface sont étendus, pas dupliqués. Les outils externes (ffmpeg, ffprobe, réseau) sont toujours injectables et jamais exécutés par les tests.

**Tech Stack:** Python 3.12 stdlib (`urllib`, `threading`, `concurrent.futures`, `subprocess`), Flask 3, ffmpeg/ffprobe (déjà dans l'image), API LibriVox et Internet Archive (JSON), API Prowlarr v1, API qBittorrent WebUI v2, JS/CSS vanilla.

**Spec:** `docs/superpowers/specs/2026-09-24-bookmallow-store-design.md` (et, pour la base, `docs/superpowers/specs/2026-09-23-bookmallow-design.md`)

## Global Constraints

- Dépôt `/home/clem/bookmallow`, branche `feat/store` (créée, spec commitée). Commits en anglais, chaque message se termine par `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Rien sous `.superpowers/` n'est commité.
- `from __future__ import annotations` en tête de chaque module ; aucune nouvelle dépendance Python (stdlib + Flask uniquement).
- Tests : `.venv/bin/pytest -q` depuis la racine (153 tests verts au départ, `-W error::ResourceWarning` actif). Les tests n'exécutent jamais `ffmpeg`, `ffprobe`, ni aucune requête réseau : `fetch`, `transport`, `popen`, `prober`, `sleep`, `clock` sont injectés.
- Compatibilité : `state.json` reste en version 1 ; les nouveaux champs de `Job` ont des défauts ; les 153 tests existants doivent rester verts sans modification autre que celles listées dans une tâche.
- Rétention partagée : `MAX_FILES` compte MP3 et M4B ensemble ; fichiers partiels `<stem>.part.<ext>` ignorés et nettoyés au démarrage ; dossier de travail `DATA_DIR/.work/<job_id>/` nettoyé après chaque job et au démarrage.
- Variables (spec §8) : `STORE_ENABLED=1`, `STORE_LIBRIVOX=1`, `STORE_ARCHIVE=1`, `PROWLARR_URL=""`, `PROWLARR_API_KEY=""`, `QBT_URL=""`, `QBT_USER=""`, `QBT_PASSWORD=""`, `QBT_CATEGORY=bookmallow`, `QBT_PATH_MAP=/downloads:/incoming`, `TORRENT_STALL_HOURS=12`, `BOOK_BITRATE=64k`, `STORE_TIMEOUT_S=20`. Volet torrent actif si et seulement si `PROWLARR_URL`, `PROWLARR_API_KEY` et `QBT_URL` sont tous renseignés.
- Codes d'erreur ajoutés (spec §10) : `store_disabled`, `not_found`, `provider_error`, `no_tracks`, `no_audio`, `torrent_add`, `torrent_error`, `torrent_stalled`, `qbt_auth` ; les codes v1 (`ffmpeg`, `no_space`, `interrupted`, `internal`, …) sont réutilisés. Chaque code a une clé `e_<code>` dans les deux langues de `I18N`.
- API (spec §7) : `GET /api/store/search?q=&lang=fr|en|all` → 200 `{results, providers}` | 400 | 503 ; `POST /api/store/jobs {key|source+source_id, quality?}` → 201 `{jobs}` | 400 | 404 | 409. `q` : 2 à 100 caractères après `strip()`.
- Frontend : aucune ressource externe (scripts/styles/polices) ; toutes les chaînes dans `I18N.fr` et `I18N.en` avec parité (test existant, indentation 4/6 espaces) ; aucun `innerHTML`.
- Palette et composants v1 réutilisés (`.card`, `.chip`, `.pill`, `.badge`, `.item`, `.thumb`, `.btn`), tokens `--pink-strong #E75A8C`, `--lilac #C9B6F2`, `--mint #BDEBD5`.
- Version livrée : `1.1.0` (tag `v1.1.0` après CI verte).

---

## File Structure

```
bookmallow/
  config.py            (modifié) champs store_*, prowlarr_*, qbt_*, torrent_stall_hours, book_bitrate, store_timeout_s ; torrent_enabled, work_dir, path_map
  jobs.py              (modifié) kind, source, source_id, author, language, torrent_hash, cover ; new_book_job()
  retention.py         (modifié) AUDIO_SUFFIXES, is_partial(), part_path(), list_audio() (list_mp3 = alias)
  procutil.py          (nouveau) StderrTail, terminate_process_groups, parse_progress_line, progress_percent, unlink_quietly, escape_ffmetadata — extraits de converter.py
  converter.py         (modifié) importe procutil, part_path via retention
  jobqueue.py          (modifié) submit_book(), _process_book(), recover() étendu, _current générique
  app.py               (modifié) routes /api/store/*, build_state (store, kind/author/language), resolve_file .m4b, CSP, mimetype m4b
  store/__init__.py    providers_available(config)
  store/models.py      StoreError, Track, BookPlan, SearchResult, lang_code(), parse_runtime()
  store/http.py        get_json(), get_bytes(), build_url(), USER_AGENT
  store/providers/__init__.py (vide)
  store/providers/librivox.py  search(), plan()
  store/providers/archive.py   search(), plan()
  store/providers/prowlarr.py  search()
  store/qbittorrent.py QbtClient, TorrentInfo, QbtError
  store/search.py      SearchCache, unified_search(), resolve_result()
  store/assemble.py    AssembleRequest, concat_list(), chapters_from_tracks(), ffmetadata(), ffmpeg_command(), Assembly
  store/torrent.py     natural_key(), map_path(), list_audio_files(), ffprobe(), TorrentAcquisition
  templates/index.html, static/app.js, static/style.css (modifiés)
tests/
  test_config.py, test_jobs_state.py, test_retention.py, test_app.py, test_jobqueue.py, test_frontend.py (modifiés)
  test_store_models.py, test_store_http.py, test_store_librivox.py, test_store_archive.py, test_store_prowlarr.py,
  test_store_qbittorrent.py, test_store_search.py, test_store_assemble.py, test_store_torrent.py (nouveaux)
README.md, CHANGELOG.md, docker-compose.yml, bookmallow/__init__.py (version), /home/clem/bookmallow-stack/{docker-compose.yml,.env}
```

---

### Task 1 : Config, modèle de job, rétention audio et téléchargement M4B

**Files:**
- Modify: `bookmallow/config.py`, `bookmallow/jobs.py`, `bookmallow/retention.py`, `bookmallow/converter.py:45-49`, `bookmallow/app.py:24-30,37-83,226-232`
- Test: `tests/test_config.py`, `tests/test_jobs_state.py`, `tests/test_retention.py`, `tests/test_app.py`

**Interfaces:**
- Produces (`config.py`) : champs `Config.store_enabled: bool = True`, `store_librivox: bool = True`, `store_archive: bool = True`, `prowlarr_url: str = ""`, `prowlarr_api_key: str = ""`, `qbt_url: str = ""`, `qbt_user: str = ""`, `qbt_password: str = ""`, `qbt_category: str = "bookmallow"`, `qbt_path_map: str = "/downloads:/incoming"`, `torrent_stall_hours: float = 12.0`, `book_bitrate: str = "64k"`, `store_timeout_s: float = 20.0` ; propriétés `torrent_enabled -> bool`, `torrent_config_state -> "enabled"|"partial"|"disabled"`, `work_dir -> Path` (= `data_dir / ".work"`), `path_map -> tuple[str, str]`.
- Produces (`jobs.py`) : champs `Job.kind: str = "youtube"`, `source: str | None`, `source_id: str | None`, `author: str | None`, `language: str | None`, `torrent_hash: str | None`, `cover: str | None` ; `new_book_job(source, source_id, title, author, language, duration, cover, quality) -> Job` (avec `url=""`, `video_id=f"{source}:{source_id}"`, `kind="book"`).
- Produces (`retention.py`) : `AUDIO_SUFFIXES = (".mp3", ".m4b")`, `is_partial(name) -> bool`, `part_path(out_path: Path) -> Path` (`<stem>.part<suffix>`), `list_audio(directory) -> list[Path]`, `list_mp3 = list_audio`.
- Produces (`app.py`) : `resolve_file` accepte `.mp3` et `.m4b` ; `build_state().files[*]` gagne `kind`, `author`, `language` ; téléchargement `.m4b` servi en `audio/mp4`.

- [ ] **Step 1 : Tests**

Ajouter à `tests/test_config.py` :
```python
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
```

Ajouter à `tests/test_jobs_state.py` :
```python
from bookmallow.jobs import new_book_job


def test_job_defaults_keep_v1_shape():
    j = new_job("u", "v", "64")
    assert j.kind == "youtube" and j.source is None and j.author is None and j.torrent_hash is None and j.cover is None


def test_v1_state_dict_without_new_fields_still_loads():
    old = {"id": "abcd1234", "url": "u", "video_id": "v", "quality": "64", "status": "done", "title": "T"}
    j = Job.from_dict(old)
    assert j.kind == "youtube" and j.language is None


def test_new_book_job():
    j = new_book_job("librivox", "904", "Boule de suif", "Guy de Maupassant", "fr", 15251, "https://c/x.jpg", "64")
    assert j.kind == "book" and j.source == "librivox" and j.source_id == "904"
    assert j.video_id == "librivox:904" and j.url == "" and j.title == "Boule de suif"
    assert j.author == "Guy de Maupassant" and j.language == "fr" and j.duration == 15251
    assert j.cover == "https://c/x.jpg" and j.thumbnail == "https://c/x.jpg" and j.quality == "64"
    assert j.to_dict()["kind"] == "book"
```

Ajouter à `tests/test_retention.py` :
```python
def test_list_audio_mixes_mp3_and_m4b_and_skips_partials(tmp_path):
    make(tmp_path, "a.mp3", 30)
    make(tmp_path, "b.m4b", 10)
    make(tmp_path, "c.part.m4b", 0)
    make(tmp_path, "d.part.mp3", 0)
    make(tmp_path, "e.m4a", 0)
    assert [p.name for p in retention.list_audio(tmp_path)] == ["b.m4b", "a.mp3"]
    assert retention.list_mp3 is retention.list_audio


def test_part_path_and_is_partial(tmp_path):
    assert retention.part_path(tmp_path / "Livre [x].m4b") == tmp_path / "Livre [x].part.m4b"
    assert retention.part_path(tmp_path / "Titre [id].mp3").name == "Titre [id].part.mp3"
    assert retention.is_partial("x.part.m4b") and retention.is_partial("x.part.mp3") and not retention.is_partial("x.mp3")


def test_prune_counts_both_kinds(tmp_path):
    make(tmp_path, "old.mp3", 300)
    make(tmp_path, "mid.m4b", 200)
    make(tmp_path, "new.mp3", 100)
    deleted = retention.prune(tmp_path, 2)
    assert [p.name for p in deleted] == ["old.mp3"]
```

Ajouter à `tests/test_app.py` :
```python
def test_download_and_resolve_m4b(client, config):
    (config.data_dir / "Livre [Auteur].m4b").write_bytes(b"m4b-bytes")
    (config.data_dir / "wip.part.m4b").write_bytes(b"w")
    assert resolve_file(config.data_dir, "Livre [Auteur].m4b") == "Livre [Auteur].m4b"
    assert resolve_file(config.data_dir, "wip.part.m4b") is None
    r = client.get("/api/files/Livre%20%5BAuteur%5D.m4b")
    assert r.status_code == 200 and r.mimetype == "audio/mp4" and r.data == b"m4b-bytes"
    r.close()
    d = client.get("/api/state").get_json()
    f = next(x for x in d["files"] if x["name"] == "Livre [Auteur].m4b")
    assert f["kind"] == "book" and f["author"] is None and f["language"] is None


def test_state_files_carry_book_fields_from_job(client, config):
    from bookmallow.jobs import new_book_job
    job = new_book_job("librivox", "904", "Boule de suif", "Guy de Maupassant", "fr", 15251, None, "64")
    job.status, job.filename = Status.DONE, "Boule de suif [Guy de Maupassant].m4b"
    client.queue.jobs.append(job)
    (config.data_dir / job.filename).write_bytes(b"x")
    f = client.get("/api/state").get_json()["files"][0]
    assert (f["kind"], f["author"], f["language"], f["title"]) == ("book", "Guy de Maupassant", "fr", "Boule de suif")
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_config.py tests/test_jobs_state.py tests/test_retention.py tests/test_app.py -q` → FAIL sur les nouveaux tests uniquement.

- [ ] **Step 3 : Implémenter `config.py`**

Ajouter après `_TRUTHY` :
```python
_FALSY = {"0", "false", "no", "off"}
_BITRATE = re.compile(r"^\d{2,3}k$")
```
(`import re` en tête.) Ajouter à la dataclass `Config`, après `force_https: bool` :
```python
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
```
Ajouter les helpers :
```python
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


def _url(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip().rstrip("/")
```
Et dans `load()`, compléter le constructeur :
```python
        store_enabled=_bool(env, "STORE_ENABLED", True),
        store_librivox=_bool(env, "STORE_LIBRIVOX", True),
        store_archive=_bool(env, "STORE_ARCHIVE", True),
        prowlarr_url=_url(env, "PROWLARR_URL"),
        prowlarr_api_key=env.get("PROWLARR_API_KEY", "").strip(),
        qbt_url=_url(env, "QBT_URL"),
        qbt_user=env.get("QBT_USER", ""),
        qbt_password=env.get("QBT_PASSWORD", ""),
        qbt_category=env.get("QBT_CATEGORY", "").strip() or "bookmallow",
        qbt_path_map=env.get("QBT_PATH_MAP", "").strip() or "/downloads:/incoming",
        torrent_stall_hours=_float(env, "TORRENT_STALL_HOURS", 12.0, 0.1),
        book_bitrate=_bitrate(env, "BOOK_BITRATE", "64k"),
        store_timeout_s=_float(env, "STORE_TIMEOUT_S", 20.0, 1.0),
```
(`_float` refuse `< minimum` ; `TORRENT_STALL_HOURS=0` et `STORE_TIMEOUT_S=0.5` lèvent donc bien.)

- [ ] **Step 4 : Implémenter `jobs.py`**

Ajouter à `Job` après `finished_at` :
```python
    kind: str = "youtube"
    source: str | None = None
    source_id: str | None = None
    author: str | None = None
    language: str | None = None
    torrent_hash: str | None = None
    cover: str | None = None
```
Ajouter après `new_job` :
```python
def new_book_job(source: str, source_id: str, title: str, author: str | None, language: str | None,
                 duration: int | None, cover: str | None, quality: str) -> Job:
    """A store acquisition job; `video_id` doubles as the de-duplication key `<source>:<source_id>`."""
    return Job(id=uuid.uuid4().hex[:8], url="", video_id=f"{source}:{source_id}", quality=quality, kind="book",
               source=source, source_id=source_id, title=title, author=author, language=language,
               duration=duration, cover=cover, thumbnail=cover)
```

- [ ] **Step 5 : Implémenter `retention.py`**

Remplacer le haut du module (jusqu'à `list_mp3` inclus) par :
```python
"""Keep only the newest MAX_FILES audio files (spec §6.5) and clean up partial files (spec §6.8)."""
from __future__ import annotations

import stat as _stat
from pathlib import Path

AUDIO_SUFFIXES = (".mp3", ".m4b")
PART_MARK = ".part."
PART_SUFFIX = ".part.mp3"  # historical name, still used by converter tests


def stat_is_regular(st) -> bool:
    return _stat.S_ISREG(st.st_mode)


def is_partial(name: str) -> bool:
    return PART_MARK in name


def part_path(out_path: Path) -> Path:
    """`Title.m4b` → `Title.part.m4b`: the file being written, ignored by retention."""
    return out_path.with_name(out_path.stem + ".part" + out_path.suffix)


def list_audio(directory: Path) -> list[Path]:
    """Finished MP3/M4B files, newest first. Partial files are skipped, as are files that vanish mid-listing."""
    entries: list[tuple[float, str, Path]] = []
    for path in Path(directory).iterdir():
        if path.suffix.lower() not in AUDIO_SUFFIXES or is_partial(path.name):
            continue
        try:
            st = path.stat()
        except FileNotFoundError:
            continue
        if not stat_is_regular(st):
            continue
        entries.append((st.st_mtime, path.name, path))
    entries.sort(reverse=True)
    return [path for _, _, path in entries]


list_mp3 = list_audio
```
`prune`, `next_to_go`, `remove_partials` restent identiques (ils appellent `list_mp3`, qui est désormais l'alias).

Dans `converter.py`, remplacer la propriété `part_path` de `ConvertRequest` par :
```python
    @property
    def part_path(self) -> Path:
        return part_path(self.out_path)
```
et l'import `from .retention import PART_SUFFIX` par `from .retention import part_path`.

- [ ] **Step 6 : Implémenter `app.py`**

`resolve_file` :
```python
def resolve_file(data_dir: Path, name: str) -> str | None:
    """Return `name` only if it is exactly the name of a finished MP3/M4B sitting in data_dir."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if not name.lower().endswith(retention.AUDIO_SUFFIXES) or retention.is_partial(name):
        return None
    return name if name in os.listdir(data_dir) else None
```
Dans `build_state` : `files = retention.list_audio(config.data_dir)` et, dans le dict de chaque fichier, ajouter :
```python
            "kind": "book" if (job and job.get("kind") == "book") or path.suffix.lower() == ".m4b" else "youtube",
            "author": job.get("author") if job else None,
            "language": job.get("language") if job else None,
```
Dans `api_download` :
```python
        mimetype = "audio/mp4" if real.lower().endswith(".m4b") else None
        return send_from_directory(config.data_dir, real, as_attachment=True, conditional=True, max_age=0, mimetype=mimetype)
```

- [ ] **Step 7 : Vérifier** — `.venv/bin/pytest -q` → tous verts (153 + nouveaux).

- [ ] **Step 8 : Commit**

```bash
git add bookmallow/config.py bookmallow/jobs.py bookmallow/retention.py bookmallow/converter.py bookmallow/app.py tests/test_config.py tests/test_jobs_state.py tests/test_retention.py tests/test_app.py
git commit -m "feat(store): config, book job fields, shared MP3/M4B retention and M4B downloads

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2 : `store/models.py`, `store/http.py`, `store/__init__.py`

**Files:**
- Create: `bookmallow/store/__init__.py`, `bookmallow/store/models.py`, `bookmallow/store/http.py`, `bookmallow/store/providers/__init__.py` (vide)
- Test: `tests/test_store_models.py`, `tests/test_store_http.py`

**Interfaces:**
- Produces (`models.py`) : `class StoreError(Exception)` (`code`, `detail`) ; `@dataclass Track(location: str, duration: float | None = None, title: str = "")` ; `@dataclass BookPlan(title, author, language, duration: int | None, cover: str | None, tracks: list[Track])` ; `@dataclass SearchResult(source, source_id, title, author=None, language=None, duration=None, size_bytes=None, seeders=None, cover=None, url=None, download=None, alt_ids: list[str] = [])` avec `key` (property, `f"{source}:{source_id}"`) et `public() -> dict` (sans `download`, avec `key`) ; `lang_code(value) -> str | None` ; `parse_runtime(text) -> int | None`.
- Produces (`http.py`) : `USER_AGENT`, `build_url(url, params) -> str` (`doseq=True`), `get_json(url, params=None, timeout=20.0, headers=None) -> Any`, `get_bytes(url, timeout=10.0, max_bytes=5_000_000) -> tuple[bytes, str]` (contenu, content-type). Toutes lèvent `StoreError("provider_error", detail)`.
- Produces (`store/__init__.py`) : `providers_available(config) -> dict[str, str]` avec clés `librivox`, `archive`, `prowlarr` et valeurs `"enabled"|"disabled"|"partial"`.

- [ ] **Step 1 : Tests**

`tests/test_store_models.py` :
```python
from __future__ import annotations

import pytest

from bookmallow.store import providers_available
from bookmallow.store.models import BookPlan, SearchResult, StoreError, Track, lang_code, parse_runtime


def test_search_result_key_and_public():
    r = SearchResult("prowlarr", "abc", "Titre", download="magnet:?xt=1", seeders=3)
    d = r.public()
    assert r.key == "prowlarr:abc" and d["key"] == "prowlarr:abc"
    assert "download" not in d and d["seeders"] == 3 and d["alt_ids"] == []


@pytest.mark.parametrize("value,code", [
    ("French", "fr"), ("fre", "fr"), ("fra", "fr"), ("fr", "fr"), ("English", "en"), ("eng", "en"),
    ("German", "de"), ("spa", "es"), ("Multilingual", "mul"), (None, None), ("", None), ("Klingon", None),
])
def test_lang_code(value, code):
    assert lang_code(value) == code


@pytest.mark.parametrize("text,seconds", [
    ("39:33:23", 142403), ("40:46", 2446), ("789.52", 790), ("12", 12), ("", None), (None, None), ("abc", None),
])
def test_parse_runtime(text, seconds):
    assert parse_runtime(text) == seconds


def test_store_error_and_plan_shape():
    exc = StoreError("no_tracks", "empty")
    assert exc.code == "no_tracks" and str(exc) == "empty"
    plan = BookPlan("T", None, "fr", 10, None, [Track("https://x/1.mp3", 5.0, "Un")])
    assert plan.tracks[0].title == "Un"


def test_providers_available(config):
    from dataclasses import replace
    assert providers_available(config) == {"librivox": "enabled", "archive": "enabled", "prowlarr": "disabled"}
    c = replace(config, store_librivox=False, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    assert providers_available(c) == {"librivox": "disabled", "archive": "enabled", "prowlarr": "enabled"}
    c = replace(config, store_enabled=False)
    assert providers_available(c) == {"librivox": "disabled", "archive": "disabled", "prowlarr": "disabled"}
```

`tests/test_store_http.py` :
```python
from __future__ import annotations

import io
import urllib.error

import pytest

from bookmallow.store import http
from bookmallow.store.models import StoreError


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str = "application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_build_url_encodes_and_repeats_lists():
    url = http.build_url("https://a/b", {"q": "bo ule", "fl[]": ["x", "y"], "n": 3})
    assert url == "https://a/b?q=bo+ule&fl%5B%5D=x&fl%5B%5D=y&n=3"
    assert http.build_url("https://a/b", None) == "https://a/b"


def test_get_json_success(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        return FakeResponse(b'{"ok": 1}')

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    assert http.get_json("https://a/b", {"q": "x"}, timeout=7) == {"ok": 1}
    assert seen == {"url": "https://a/b?q=x", "ua": http.USER_AGENT, "timeout": 7}


@pytest.mark.parametrize("boom", [
    urllib.error.HTTPError("https://a/b", 503, "down", {}, None),
    urllib.error.URLError("dns"),
    TimeoutError("slow"),
])
def test_get_json_errors_become_store_error(monkeypatch, boom):
    def fake_urlopen(req, timeout):
        raise boom

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(StoreError) as exc:
        http.get_json("https://a/b")
    assert exc.value.code == "provider_error" and "a" in exc.value.detail


def test_get_json_unreadable(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"<html>"))
    with pytest.raises(StoreError) as exc:
        http.get_json("https://a/b")
    assert exc.value.code == "provider_error"


def test_get_bytes_caps_size_and_returns_type(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"x" * 10, "image/jpeg"))
    body, ctype = http.get_bytes("https://a/c.jpg", max_bytes=100)
    assert body == b"x" * 10 and ctype == "image/jpeg"
    with pytest.raises(StoreError):
        http.get_bytes("https://a/c.jpg", max_bytes=5)
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_models.py tests/test_store_http.py -q` → FAIL (module absent).

- [ ] **Step 3 : Implémenter**

`bookmallow/store/providers/__init__.py` : fichier vide.

`bookmallow/store/models.py` :
```python
"""Data shapes shared by the store providers, the search layer and the acquisition pipelines (spec §5)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_LANG_CODES = {
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr", "français": "fr", "francais": "fr",
    "en": "en", "eng": "en", "english": "en",
    "de": "de", "ger": "de", "deu": "de", "german": "de",
    "es": "es", "spa": "es", "spanish": "es",
    "it": "it", "ita": "it", "italian": "it",
    "pt": "pt", "por": "pt", "portuguese": "pt",
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "la": "la", "lat": "la", "latin": "la",
    "mul": "mul", "multilingual": "mul",
}
_RUNTIME = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)\s*$")


class StoreError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class Track:
    location: str  # http(s) URL or local path
    duration: float | None = None
    title: str = ""


@dataclass
class BookPlan:
    title: str
    author: str | None
    language: str | None
    duration: int | None
    cover: str | None
    tracks: list[Track] = field(default_factory=list)


@dataclass
class SearchResult:
    source: str
    source_id: str
    title: str
    author: str | None = None
    language: str | None = None
    duration: int | None = None
    size_bytes: int | None = None
    seeders: int | None = None
    cover: str | None = None
    url: str | None = None
    download: str | None = None  # magnet / .torrent URL, never sent to the browser
    alt_ids: list[str] = field(default_factory=list)  # e.g. the Internet Archive id of a LibriVox book

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def public(self) -> dict:
        data = asdict(self)
        data.pop("download")
        data["key"] = self.key
        return data


def lang_code(value: str | None) -> str | None:
    if not value:
        return None
    return _LANG_CODES.get(str(value).strip().lower())


def parse_runtime(text: str | None) -> int | None:
    """'39:33:23', '40:46', '789.52' or '12' → whole seconds; None when unreadable."""
    if text is None:
        return None
    m = _RUNTIME.match(str(text))
    if not m:
        return None
    h, mn, s = m.groups()
    parts = [p for p in (h, mn) if p is not None]  # "40:46" → parts == ["40"] (minutes); "1:02:03" → ["1", "02"]
    total = float(s)
    if len(parts) == 1:
        total += int(parts[0]) * 60
    elif len(parts) == 2:
        total += int(parts[0]) * 3600 + int(parts[1]) * 60
    return int(round(total))
```
`bookmallow/store/http.py` :
```python
"""Tiny HTTP helpers for the store: JSON GET and small binary GET, stdlib only."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .. import __version__
from .models import StoreError

USER_AGENT = f"Bookmallow/{__version__} (+https://github.com/clemdepernet/bookmallow)"


def build_url(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}?{urllib.parse.urlencode(params, doseq=True)}"


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


def _open(url: str, timeout: float, headers: Mapping[str, str] | None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*", **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise StoreError("provider_error", f"{_host(url)}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise StoreError("provider_error", f"{_host(url)}: {reason}") from exc


def get_json(url: str, params: Mapping[str, Any] | None = None, timeout: float = 20.0,
             headers: Mapping[str, str] | None = None) -> Any:
    full = build_url(url, params)
    with _open(full, timeout, headers) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise StoreError("provider_error", f"{_host(url)}: unreadable JSON") from exc


def get_bytes(url: str, timeout: float = 10.0, max_bytes: int = 5_000_000) -> tuple[bytes, str]:
    """Download a small file (cover art). Returns (content, content-type)."""
    with _open(url, timeout, None) as resp:
        body = resp.read(max_bytes + 1)
        ctype = str(resp.headers.get("Content-Type", "")).split(";")[0].strip()
    if len(body) > max_bytes:
        raise StoreError("provider_error", f"{_host(url)}: file larger than {max_bytes} bytes")
    return body, ctype
```

`bookmallow/store/__init__.py` :
```python
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
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_store_models.py tests/test_store_http.py -q` → verts ; suite complète verte.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/store tests/test_store_models.py tests/test_store_http.py
git commit -m "feat(store): shared models, stdlib HTTP helpers and provider availability

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3 : Fournisseur LibriVox

**Files:**
- Create: `bookmallow/store/providers/librivox.py`
- Test: `tests/test_store_librivox.py`

**Interfaces:**
- Consumes: `models.SearchResult/BookPlan/Track/StoreError/lang_code`, `http.get_json` (T2).
- Produces: `API = "https://librivox.org/api/feed/audiobooks"`, `search(q, lang, fetch=get_json, timeout=20.0, limit=25) -> list[SearchResult]` (source `"librivox"`, `alt_ids=[<identifiant Internet Archive>]`), `plan(book_id, fetch=get_json, timeout=20.0) -> BookPlan`, `iarchive_id(url) -> str | None`.
- Faits d'API vérifiés : la recherche par titre exige le préfixe `^` (`title=^pride`) ; `author=maupassant` fonctionne sans préfixe ; aucun résultat renvoie `{"error": "Audiobooks could not be found"}` ; avec `extended=1&coverart=1` chaque livre a `id, title, language ("French"/"English"), totaltimesecs, authors[{first_name,last_name}], url_librivox, url_iarchive, coverart_jpg, coverart_thumbnail, sections[{section_number, title, listen_url, playtime}]`.

- [ ] **Step 1 : Tests**

`tests/test_store_librivox.py` :
```python
from __future__ import annotations

import pytest

from bookmallow.store.models import StoreError
from bookmallow.store.providers import librivox as lv

BOOK = {
    "id": "904", "title": "Boule de suif", "language": "French", "totaltimesecs": "15251",
    "authors": [{"first_name": "Guy de", "last_name": "Maupassant"}],
    "url_librivox": "https://librivox.org/boule-de-suif-by-guy-de-maupassant/",
    "url_iarchive": "https://www.archive.org/details/bouledesuif_0904_librivox",
    "coverart_jpg": "https://www.archive.org/download/LibrivoxCdCoverArt4/Ball_of_Fat_1005.jpg",
    "coverart_thumbnail": "https://www.archive.org/download/LibrivoxCdCoverArt4/Ball_of_Fat_1005_thumb.jpg",
    "sections": [
        {"section_number": "2", "title": "Partie 2", "listen_url": "https://archive.org/download/bouledesuif_0904_librivox/boule_02.mp3", "playtime": "1400"},
        {"section_number": "1", "title": "Partie 1", "listen_url": "https://archive.org/download/bouledesuif_0904_librivox/boule_01.mp3", "playtime": "1300.5"},
    ],
}
BOOK_EN = {**BOOK, "id": "1", "title": "Ball of Fat", "language": "English", "sections": []}


def fetcher(mapping):
    """mapping: param name → payload; the fetcher picks by whichever of title/author/id is present."""
    calls = []

    def fetch(url, params=None, timeout=20.0, headers=None):
        calls.append(dict(params or {}))
        for key in ("id", "title", "author"):
            if key in (params or {}):
                return mapping.get(key, {"error": "Audiobooks could not be found"})
        return {"error": "Audiobooks could not be found"}

    fetch.calls = calls
    return fetch


def test_search_merges_title_and_author_and_filters_language():
    fetch = fetcher({"title": {"books": [BOOK, BOOK_EN]}, "author": {"books": [BOOK]}})
    results = lv.search("boule", "fr", fetch=fetch)
    assert [r.source_id for r in results] == ["904"]
    r = results[0]
    assert r.source == "librivox" and r.title == "Boule de suif" and r.author == "Guy de Maupassant"
    assert r.language == "fr" and r.duration == 15251 and r.cover == BOOK["coverart_jpg"]
    assert r.url == BOOK["url_librivox"] and r.alt_ids == ["bouledesuif_0904_librivox"]
    assert fetch.calls[0]["title"] == "^boule" and fetch.calls[1]["author"] == "boule"
    assert fetch.calls[0]["extended"] == "1" and fetch.calls[0]["coverart"] == "1" and fetch.calls[0]["format"] == "json"


def test_search_all_languages_and_no_results():
    fetch = fetcher({"title": {"books": [BOOK, BOOK_EN]}})
    assert [r.language for r in lv.search("boule", "all", fetch=fetch)] == ["fr", "en"]
    assert lv.search("zzz", "all", fetch=fetcher({})) == []


def test_search_propagates_store_error():
    def boom(url, params=None, timeout=20.0, headers=None):
        raise StoreError("provider_error", "down")
    with pytest.raises(StoreError):
        lv.search("x", "all", fetch=boom)


def test_plan_orders_sections_and_reads_durations():
    fetch = fetcher({"id": {"books": [BOOK]}})
    plan = lv.plan("904", fetch=fetch)
    assert fetch.calls[0]["id"] == "904"
    assert plan.title == "Boule de suif" and plan.author == "Guy de Maupassant" and plan.language == "fr"
    assert plan.duration == 15251 and plan.cover == BOOK["coverart_jpg"]
    assert [t.title for t in plan.tracks] == ["Partie 1", "Partie 2"]
    assert plan.tracks[0].location.endswith("boule_01.mp3") and plan.tracks[0].duration == 1300.5


def test_plan_errors():
    with pytest.raises(StoreError) as exc:
        lv.plan("999", fetch=fetcher({}))
    assert exc.value.code == "not_found"
    with pytest.raises(StoreError) as exc:
        lv.plan("1", fetch=fetcher({"id": {"books": [BOOK_EN]}}))
    assert exc.value.code == "no_tracks"


def test_iarchive_id():
    assert lv.iarchive_id("https://www.archive.org/details/bouledesuif_0904_librivox") == "bouledesuif_0904_librivox"
    assert lv.iarchive_id("https://archive.org/details/x_y/") == "x_y"
    assert lv.iarchive_id(None) is None and lv.iarchive_id("https://example.com/") is None
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_librivox.py -q` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/store/providers/librivox.py` :
```python
"""LibriVox catalogue: public-domain audiobooks read by volunteers (spec §6.1, §6.3)."""
from __future__ import annotations

import re
from typing import Callable

from ..http import get_json
from ..models import BookPlan, SearchResult, StoreError, Track, lang_code

API = "https://librivox.org/api/feed/audiobooks"
LANG_NAMES = {"fr": "French", "en": "English"}
_IA = re.compile(r"archive\.org/details/([^/?#]+)")
Fetch = Callable[..., object]


def iarchive_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _IA.search(url)
    return m.group(1) if m else None


def _author(book: dict) -> str | None:
    names = []
    for a in book.get("authors") or []:
        full = " ".join(p for p in (str(a.get("first_name") or "").strip(), str(a.get("last_name") or "").strip()) if p)
        if full:
            names.append(full)
    return ", ".join(names[:2]) or None


def _int(value) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _result(book: dict) -> SearchResult:
    ia = iarchive_id(book.get("url_iarchive"))
    return SearchResult(
        source="librivox",
        source_id=str(book.get("id")),
        title=str(book.get("title") or "Sans titre"),
        author=_author(book),
        language=lang_code(book.get("language")),
        duration=_int(book.get("totaltimesecs")),
        cover=book.get("coverart_jpg") or book.get("coverart_thumbnail"),
        url=book.get("url_librivox"),
        alt_ids=[ia] if ia else [],
    )


def _books(payload) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("books"), list):
        return [b for b in payload["books"] if isinstance(b, dict)]
    return []  # {"error": "Audiobooks could not be found"} or anything unexpected


def search(q: str, lang: str, fetch: Fetch = get_json, timeout: float = 20.0, limit: int = 25) -> list[SearchResult]:
    common = {"format": "json", "extended": "1", "coverart": "1", "limit": str(limit)}
    seen: dict[str, SearchResult] = {}
    for params in ({"title": f"^{q}"}, {"author": q}):
        for book in _books(fetch(API, {**params, **common}, timeout=timeout)):
            result = _result(book)
            if lang != "all" and result.language != lang:
                continue
            seen.setdefault(result.source_id, result)
    return list(seen.values())[:limit]


def plan(book_id: str, fetch: Fetch = get_json, timeout: float = 20.0) -> BookPlan:
    books = _books(fetch(API, {"id": str(book_id), "format": "json", "extended": "1", "coverart": "1"}, timeout=timeout))
    if not books:
        raise StoreError("not_found", f"LibriVox book {book_id} not found")
    book = books[0]
    sections = [s for s in (book.get("sections") or []) if isinstance(s, dict) and s.get("listen_url")]
    sections.sort(key=lambda s: _int(s.get("section_number")) or 0)
    if not sections:
        raise StoreError("no_tracks", "LibriVox returned no sections for this book")
    result = _result(book)
    tracks = [Track(location=str(s["listen_url"]), duration=_float(s.get("playtime")), title=str(s.get("title") or ""))
              for s in sections]
    return BookPlan(title=result.title, author=result.author, language=result.language,
                    duration=result.duration, cover=result.cover, tracks=tracks)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_store_librivox.py -q` → verts.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/store/providers/librivox.py tests/test_store_librivox.py
git commit -m "feat(store): LibriVox provider (search and chapter plan)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4 : Fournisseur Internet Archive

**Files:**
- Create: `bookmallow/store/providers/archive.py`
- Test: `tests/test_store_archive.py`

**Interfaces:**
- Consumes: T2 models/http.
- Produces: `search(q, lang, fetch=get_json, timeout=20.0, limit=25) -> list[SearchResult]` (source `"archive"`), `plan(identifier, fetch=get_json, timeout=20.0) -> BookPlan`, `pick_tracks(files) -> list[dict]` (une entrée par piste, `_64kb.mp3` préféré), `escape_lucene(text) -> str`.
- Faits vérifiés : `advancedsearch.php` renvoie `response.docs[{identifier,title,creator,language ("fre"/"eng"),runtime ("39:33:23")}]` ; `creator` peut être une liste ; `/metadata/<id>` renvoie `{metadata:{title,creator,language,runtime}, files:[{name,length ("789.52" ou "13:09"),track,source,format}]}` avec plusieurs débits par chapitre (`_64kb.mp3`, `_128kb.mp3`, sans suffixe) ; un identifiant inconnu renvoie `{"error": ...}` sans `metadata` ; image d'un item : `https://archive.org/services/img/<id>`.

- [ ] **Step 1 : Tests**

`tests/test_store_archive.py` :
```python
from __future__ import annotations

import pytest

from bookmallow.store.models import StoreError
from bookmallow.store.providers import archive as ia

DOC = {"identifier": "shortstories_2103_librivox", "title": "Short Stories", "creator": ["Guy de Maupassant", "Various"],
       "language": "eng", "runtime": "39:33:23"}
META = {
    "metadata": {"identifier": "shortstories_2103_librivox", "title": "Short Stories", "creator": "Guy de Maupassant",
                 "language": "eng", "runtime": "1:00:00"},
    "files": [
        {"name": "ss_002_maupassant.mp3", "length": "700.0", "track": "2", "source": "derivative"},
        {"name": "ss_002_maupassant_64kb.mp3", "length": "700.5", "track": "2", "source": "derivative"},
        {"name": "ss_002_maupassant_128kb.mp3", "length": "700.0", "track": "2", "source": "original"},
        {"name": "ss_001_maupassant_128kb.mp3", "length": "13:09", "track": "1", "source": "original"},
        {"name": "ss_001_maupassant.mp3", "length": "789.5", "track": "1", "source": "derivative"},
        {"name": "shortstories_2103.jpg", "source": "original"},
        {"name": "__ia_thumb.jpg", "source": "derivative"},
        {"name": "readme.txt"},
    ],
}


def fetcher(payload):
    calls = []

    def fetch(url, params=None, timeout=20.0, headers=None):
        calls.append((url, dict(params or {})))
        return payload

    fetch.calls = calls
    return fetch


def test_search_builds_query_and_maps_fields():
    fetch = fetcher({"response": {"numFound": 1, "docs": [DOC, {"identifier": "noname"}]}})
    results = ia.search("maupassant (short)", "en", fetch=fetch, limit=7)
    url, params = fetch.calls[0]
    assert url == ia.SEARCH and params["rows"] == "7" and params["output"] == "json"
    assert "collection:librivoxaudio" in params["q"] and "audio_bookspoetry" in params["q"]
    assert r"maupassant \(short\)" in params["q"] and "language:(eng OR english)" in params["q"]
    assert params["fl[]"] == ["identifier", "title", "creator", "language", "runtime"]
    assert len(results) == 2
    r = results[0]
    assert r.source == "archive" and r.source_id == "shortstories_2103_librivox" and r.title == "Short Stories"
    assert r.author == "Guy de Maupassant" and r.language == "en" and r.duration == 142403
    assert r.cover == "https://archive.org/services/img/shortstories_2103_librivox"
    assert r.url == "https://archive.org/details/shortstories_2103_librivox"
    assert results[1].title == "noname" and results[1].author is None


def test_search_lang_all_has_no_language_clause():
    fetch = fetcher({"response": {"docs": []}})
    assert ia.search("x", "all", fetch=fetch) == []
    assert "language:" not in fetch.calls[0][1]["q"]


def test_pick_tracks_prefers_64kb_then_original_and_sorts_by_track():
    picked = ia.pick_tracks(META["files"])
    assert [f["name"] for f in picked] == ["ss_001_maupassant_128kb.mp3", "ss_002_maupassant_64kb.mp3"]


def test_plan_builds_tracks_cover_and_duration():
    plan = ia.plan("shortstories_2103_librivox", fetch=fetcher(META))
    assert plan.title == "Short Stories" and plan.author == "Guy de Maupassant" and plan.language == "en"
    assert plan.duration == 3600
    assert plan.cover == "https://archive.org/download/shortstories_2103_librivox/shortstories_2103.jpg"
    assert [t.location for t in plan.tracks] == [
        "https://archive.org/download/shortstories_2103_librivox/ss_001_maupassant_128kb.mp3",
        "https://archive.org/download/shortstories_2103_librivox/ss_002_maupassant_64kb.mp3"]
    assert plan.tracks[0].duration == 789.0 and plan.tracks[1].duration == 700.5
    assert plan.tracks[0].title == "ss_001_maupassant_128kb"


def test_plan_falls_back_to_summed_lengths_and_service_image():
    meta = {"metadata": {"identifier": "x", "title": "X"}, "files": [{"name": "a b.mp3", "length": "10"}, {"name": "c.mp3", "length": "5"}]}
    plan = ia.plan("x", fetch=fetcher(meta))
    assert plan.duration == 15 and plan.cover == "https://archive.org/services/img/x"
    assert plan.tracks[0].location == "https://archive.org/download/x/a%20b.mp3"


def test_plan_errors():
    with pytest.raises(StoreError) as exc:
        ia.plan("nope", fetch=fetcher({"error": "Unable to fetch nope.json"}))
    assert exc.value.code == "not_found"
    with pytest.raises(StoreError) as exc:
        ia.plan("empty", fetch=fetcher({"metadata": {"identifier": "empty"}, "files": [{"name": "r.txt"}]}))
    assert exc.value.code == "no_tracks"


def test_escape_lucene():
    assert ia.escape_lucene('a:b "c" (d) e/f') == r'a\:b \"c\" \(d\) e\/f'
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_archive.py -q` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/store/providers/archive.py` :
```python
"""Internet Archive: complements LibriVox with other free audiobook collections (spec §6.1, §6.3)."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import quote

from ..http import get_json
from ..models import BookPlan, SearchResult, StoreError, Track, lang_code, parse_runtime

SEARCH = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
DOWNLOAD = "https://archive.org/download/"
IMG = "https://archive.org/services/img/"
COLLECTIONS = "(collection:librivoxaudio OR collection:audio_bookspoetry)"
LANG_QUERY = {"fr": "(fre OR fra OR french)", "en": "(eng OR english)"}
FIELDS = ["identifier", "title", "creator", "language", "runtime"]
_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/])')
_BITRATE = re.compile(r"_(\d{2,3}kb|vbr)$", re.I)
Fetch = Callable[..., object]


def escape_lucene(text: str) -> str:
    return _LUCENE.sub(r"\\\1", text)


def _first(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value).strip() if value not in (None, "") else None


def _result(doc: dict) -> SearchResult:
    ident = str(doc.get("identifier") or "")
    return SearchResult(
        source="archive",
        source_id=ident,
        title=_first(doc.get("title")) or ident,
        author=_first(doc.get("creator")),
        language=lang_code(_first(doc.get("language"))),
        duration=parse_runtime(_first(doc.get("runtime"))),
        cover=f"{IMG}{ident}",
        url=f"https://archive.org/details/{ident}",
    )


def search(q: str, lang: str, fetch: Fetch = get_json, timeout: float = 20.0, limit: int = 25) -> list[SearchResult]:
    term = escape_lucene(q)
    query = f"{COLLECTIONS} AND (title:({term}) OR creator:({term}))"
    if lang in LANG_QUERY:
        query += f" AND language:{LANG_QUERY[lang]}"
    payload = fetch(SEARCH, {"q": query, "fl[]": FIELDS, "rows": str(limit), "output": "json"}, timeout=timeout)
    docs = payload.get("response", {}).get("docs", []) if isinstance(payload, dict) else []
    return [_result(d) for d in docs if isinstance(d, dict) and d.get("identifier")]


def _track_key(name: str) -> str:
    stem = name[:-4]
    return _BITRATE.sub("", stem)


def pick_tracks(files: list[dict]) -> list[dict]:
    """One MP3 per chapter: prefer the `_64kb` derivative, then the original, then anything; ordered by track/name."""
    groups: dict[str, list[dict]] = {}
    for f in files:
        name = str(f.get("name") or "")
        if not name.lower().endswith(".mp3"):
            continue
        groups.setdefault(_track_key(name), []).append(f)

    def rank(f: dict) -> int:
        n = str(f["name"]).lower()
        return 0 if n.endswith("_64kb.mp3") else (1 if f.get("source") == "original" else 2)

    chosen = [sorted(g, key=rank)[0] for g in groups.values()]

    def order(f: dict):
        track = str(f.get("track") or "")
        num = int(track.split("/")[0]) if track.split("/")[0].isdigit() else 10**9
        return (num, _track_key(str(f["name"])))

    return sorted(chosen, key=order)


def plan(identifier: str, fetch: Fetch = get_json, timeout: float = 20.0) -> BookPlan:
    payload = fetch(f"{META}{identifier}", None, timeout=timeout)
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata"), dict):
        raise StoreError("not_found", f"Internet Archive item {identifier} not found")
    meta = payload["metadata"]
    files = [f for f in (payload.get("files") or []) if isinstance(f, dict)]
    picked = pick_tracks(files)
    if not picked:
        raise StoreError("no_tracks", "this item has no MP3 files")
    tracks = []
    for f in picked:
        name = str(f["name"])
        length = parse_runtime(f.get("length"))
        raw = f.get("length")
        duration = float(raw) if isinstance(raw, str) and re.fullmatch(r"\d+(\.\d+)?", raw) else (float(length) if length is not None else None)
        tracks.append(Track(location=f"{DOWNLOAD}{identifier}/{quote(name)}", duration=duration, title=name[:-4]))
    images = [str(f["name"]) for f in files
              if str(f.get("name", "")).lower().endswith((".jpg", ".jpeg", ".png")) and not str(f["name"]).startswith("__ia_thumb")]
    cover = f"{DOWNLOAD}{identifier}/{quote(images[0])}" if images else f"{IMG}{identifier}"
    duration = parse_runtime(_first(meta.get("runtime")))
    if duration is None and all(t.duration is not None for t in tracks):
        duration = int(round(sum(t.duration for t in tracks)))
    return BookPlan(title=_first(meta.get("title")) or identifier, author=_first(meta.get("creator")),
                    language=lang_code(_first(meta.get("language"))), duration=duration, cover=cover, tracks=tracks)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_store_archive.py -q` → verts.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/store/providers/archive.py tests/test_store_archive.py
git commit -m "feat(store): Internet Archive provider (search, track selection, plan)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5 : Fournisseur Prowlarr et client qBittorrent

**Files:**
- Create: `bookmallow/store/providers/prowlarr.py`, `bookmallow/store/qbittorrent.py`
- Test: `tests/test_store_prowlarr.py`, `tests/test_store_qbittorrent.py`

**Interfaces:**
- Consumes: T1 `Config` (prowlarr_url, prowlarr_api_key, store_timeout_s, qbt_*), T2 models/http.
- Produces (`prowlarr.py`) : `search(q, config, fetch=get_json, limit=30) -> list[SearchResult]` (source `"prowlarr"`, `source_id` = 16 premiers hex du SHA-1 du `guid`, `download` = `magnetUrl` sinon `downloadUrl`, triés par `seeders` décroissant, `language` deviné dans le titre), `guess_language(title) -> str | None`.
- Produces (`qbittorrent.py`) : `class QbtError(StoreError)` ; `@dataclass TorrentInfo(hash, name, progress: float, state: str, content_path: str, size: int, downloaded: int)` ; `Transport = Callable[[str, str, dict | None, dict], tuple[int, str]]` (`(method, url, form_data, headers) -> (status, body)`) ; `class QbtClient(base_url, user, password, transport=None, timeout=20.0)` avec `login() -> None`, `ensure_category(name) -> None`, `add(download, category, tags: list[str]) -> None`, `find_by_tag(tag) -> TorrentInfo | None`, `info(hash) -> TorrentInfo | None`, `delete(hash, delete_files=True) -> None`. Codes : `qbt_auth` (HTTP 401/403, ou corps de login autre que vide/`Ok.`), `torrent_add` (corps d'ajout autre que vide/`Ok.`), `provider_error` (autres HTTP/erreurs réseau).
- Faits d'API (vérifiés sur qBittorrent 5.2.3) : les en-têtes `Referer`/`Origin` doivent valoir l'URL de base ; `auth/login` réussi renvoie **HTTP 204 sans corps** (les versions 4.x renvoient 200 `Ok.`) et pose un cookie `SID`/`QBT_SID_<port>` ; mot de passe faux → **401** (403 quand la session est bannie) ; `torrents/add` renvoie 200 `Ok.` (ou 204) et `Fails.` en échec ; `torrents/info?tag=<tag>` et `?hashes=<hash>` renvoient une liste JSON avec `hash, name, progress (0–1), state, content_path, size, downloaded` ; `torrents/createCategory` renvoie 409 si la catégorie existe ; `torrents/delete` prend `hashes` et `deleteFiles`.

- [ ] **Step 1 : Tests**

`tests/test_store_prowlarr.py` :
```python
from __future__ import annotations

from dataclasses import replace

import pytest

from bookmallow.store.models import StoreError
from bookmallow.store.providers import prowlarr as pw

ITEMS = [
    {"guid": "https://idx/1", "title": "Le Comte de Monte-Cristo [FR] MP3 64k", "size": 900_000_000, "seeders": 12,
     "magnetUrl": "magnet:?xt=urn:btih:AAA", "downloadUrl": "https://idx/dl/1", "infoUrl": "https://idx/t/1", "indexer": "Idx"},
    {"guid": "https://idx/2", "title": "Pride and Prejudice (English) Audiobook", "size": 400_000_000, "seeders": 40,
     "downloadUrl": "https://idx/dl/2", "infoUrl": "https://idx/t/2", "indexer": "Idx"},
    {"guid": "https://idx/3", "title": "No download here", "size": 1, "seeders": 99},
]


@pytest.fixture
def tconfig(config):
    return replace(config, prowlarr_url="http://prowlarr:9696", prowlarr_api_key="KEY", qbt_url="http://qbt:8080", store_timeout_s=7.0)


def test_search_maps_sorts_and_hides_download_from_public(tconfig):
    calls = []

    def fetch(url, params=None, timeout=20.0, headers=None):
        calls.append((url, dict(params), timeout, dict(headers)))
        return ITEMS

    results = pw.search("monte", tconfig, fetch=fetch, limit=30)
    url, params, timeout, headers = calls[0]
    assert url == "http://prowlarr:9696/api/v1/search"
    assert params == {"query": "monte", "categories": "3030", "type": "search", "limit": "30"}
    assert timeout == 7.0 and headers == {"X-Api-Key": "KEY"}
    assert [r.seeders for r in results] == [40, 12]  # item 3 dropped (no download link)
    fr = results[1]
    assert fr.source == "prowlarr" and len(fr.source_id) == 16 and fr.download == "magnet:?xt=urn:btih:AAA"
    assert fr.size_bytes == 900_000_000 and fr.language == "fr" and fr.url == "https://idx/t/1" and fr.author == "Idx"
    assert results[0].download == "https://idx/dl/2" and results[0].language == "en"
    assert "download" not in fr.public()


def test_search_requires_configuration(config):
    with pytest.raises(StoreError) as exc:
        pw.search("x", config, fetch=lambda *a, **k: [])
    assert exc.value.code == "store_disabled"


def test_search_unexpected_payload(tconfig):
    assert pw.search("x", tconfig, fetch=lambda *a, **k: {"error": "nope"}) == []


@pytest.mark.parametrize("title,lang", [
    ("Livre audio FR - Dumas", "fr"), ("Roman [French] mp3", "fr"), ("Book (VF)", "fr"), ("Novel [English]", "en"),
    ("Something EN audiobook", "en"), ("Ambiguous title", None), ("Frank Herbert Dune", None),
])
def test_guess_language(title, lang):
    assert pw.guess_language(title) == lang
```

`tests/test_store_qbittorrent.py` :
```python
from __future__ import annotations

import json

import pytest

from bookmallow.store import qbittorrent as qb


class Script:
    """Scripted transport: list of (status, body); records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, data, headers):
        self.calls.append((method, url, data, dict(headers)))
        return self.responses.pop(0)


INFO = [{"hash": "abc", "name": "Book", "progress": 0.5, "state": "downloading", "content_path": "/downloads/bookmallow/Book",
         "size": 1000, "downloaded": 500}]


@pytest.mark.parametrize("response", [(200, "Ok."), (204, "")])
def test_login_sets_headers_and_accepts_ok(response):
    t = Script([response])
    c = qb.QbtClient("http://qbt:8080/", "admin", "pw", transport=t)
    c.login()
    method, url, data, headers = t.calls[0]
    assert (method, url) == ("POST", "http://qbt:8080/api/v2/auth/login")
    assert data == {"username": "admin", "password": "pw"}
    assert headers["Referer"] == "http://qbt:8080" and headers["Origin"] == "http://qbt:8080"


@pytest.mark.parametrize("response", [(200, "Fails."), (403, "Forbidden"), (401, "Unauthorized")])
def test_login_refused(response):
    c = qb.QbtClient("http://qbt:8080", "admin", "pw", transport=Script([response]))
    with pytest.raises(qb.QbtError) as exc:
        c.login()
    assert exc.value.code == "qbt_auth"


def test_add_find_info_delete_category():
    t = Script([(200, "Ok."), (200, json.dumps(INFO)), (200, json.dumps(INFO)), (200, "[]"), (200, ""), (409, "exists"), (200, "")])
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=t)
    c.add("magnet:?xt=1", "bookmallow", ["bookmallow", "job-1234"])
    assert t.calls[0][2] == {"urls": "magnet:?xt=1", "category": "bookmallow", "tags": "bookmallow,job-1234"}
    found = c.find_by_tag("job-1234")
    assert t.calls[1][0] == "GET" and t.calls[1][1] == "http://qbt:8080/api/v2/torrents/info?tag=job-1234"
    assert found.hash == "abc" and found.progress == 0.5 and found.content_path == "/downloads/bookmallow/Book"
    assert c.info("abc").name == "Book"
    assert t.calls[2][1] == "http://qbt:8080/api/v2/torrents/info?hashes=abc"
    assert c.info("zzz") is None
    c.delete("abc")
    assert t.calls[4][1] == "http://qbt:8080/api/v2/torrents/delete" and t.calls[4][2] == {"hashes": "abc", "deleteFiles": "true"}
    c.ensure_category("bookmallow")  # 409 = already exists → fine
    c.ensure_category("other")


def test_add_failure_and_http_errors():
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=Script([(200, "Fails."), (500, "boom")]))
    with pytest.raises(qb.QbtError) as exc:
        c.add("magnet:?xt=1", "cat", [])
    assert exc.value.code == "torrent_add"
    with pytest.raises(qb.QbtError) as exc:
        c.info("abc")
    assert exc.value.code == "provider_error"


def test_default_transport_uses_cookie_jar_opener(monkeypatch):
    class Resp:
        status = 200

        def read(self):
            return b"Ok."

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_open(self, req, timeout=None):
        seen["url"], seen["data"], seen["timeout"] = req.full_url, req.data, timeout
        return Resp()

    monkeypatch.setattr(qb.urllib.request.OpenerDirector, "open", fake_open)
    c = qb.QbtClient("http://qbt:8080", "u", "p", timeout=3.0)
    c.login()
    assert seen["url"] == "http://qbt:8080/api/v2/auth/login" and seen["timeout"] == 3.0
    assert b"username=u" in seen["data"] and b"password=p" in seen["data"]
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_prowlarr.py tests/test_store_qbittorrent.py -q` → FAIL.

- [ ] **Step 3 : Implémenter `prowlarr.py`**

```python
"""Prowlarr: Clem's indexer aggregator, audiobook category 3030 (spec §6.1, §6.4). Optional."""
from __future__ import annotations

import hashlib
import re
from typing import Callable

from ...config import Config
from ..http import get_json
from ..models import SearchResult, StoreError

CATEGORY_AUDIOBOOK = "3030"
_FR = re.compile(r"(?<![a-z])(fr|french|français|francais|vf|vff|multi\W*fr)(?![a-z])", re.I)
_EN = re.compile(r"(?<![a-z])(en|eng|english|vo|vostfr)(?![a-z])", re.I)
Fetch = Callable[..., object]


def guess_language(title: str) -> str | None:
    fr, en = bool(_FR.search(title)), bool(_EN.search(title))
    if fr and not en:
        return "fr"
    if en and not fr:
        return "en"
    return None


def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def search(q: str, config: Config, fetch: Fetch = get_json, limit: int = 30) -> list[SearchResult]:
    if not config.torrent_enabled:
        raise StoreError("store_disabled", "Prowlarr is not configured")
    payload = fetch(f"{config.prowlarr_url}/api/v1/search",
                    {"query": q, "categories": CATEGORY_AUDIOBOOK, "type": "search", "limit": str(limit)},
                    timeout=config.store_timeout_s, headers={"X-Api-Key": config.prowlarr_api_key})
    if not isinstance(payload, list):
        return []
    results: list[SearchResult] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        download = item.get("magnetUrl") or item.get("downloadUrl")
        guid = str(item.get("guid") or download or "")
        if not download or not guid:
            continue
        title = str(item.get("title") or "Sans titre")
        results.append(SearchResult(
            source="prowlarr",
            source_id=hashlib.sha1(guid.encode("utf-8")).hexdigest()[:16],
            title=title,
            author=str(item.get("indexer")) if item.get("indexer") else None,
            language=guess_language(title),
            size_bytes=_int(item.get("size")),
            seeders=_int(item.get("seeders")),
            url=item.get("infoUrl"),
            download=str(download),
        ))
    results.sort(key=lambda r: (r.seeders if r.seeders is not None else -1), reverse=True)
    return results[:limit]
```

- [ ] **Step 4 : Implémenter `qbittorrent.py`**

```python
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
        status, body = self._transport("POST" if data is not None else "GET", f"{self.base_url}{path}", data, headers)
        if status in (401, 403):
            raise QbtError("qbt_auth", f"qBittorrent refused the credentials or session ({status})")
        if status not in ok_statuses:
            raise QbtError("provider_error", f"qBittorrent HTTP {status} on {path}: {body[:120]}")
        return body

    # ---- API ---------------------------------------------------------------------------------

    def login(self) -> None:
        body = self._call("/api/v2/auth/login", {"username": self._user, "password": self._password})
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
        return [TorrentInfo.from_dict(i) for i in items if isinstance(i, dict)]

    def find_by_tag(self, tag: str) -> TorrentInfo | None:
        infos = self._infos(f"tag={urllib.parse.quote(tag)}")
        return infos[0] if infos else None

    def info(self, torrent_hash: str) -> TorrentInfo | None:
        infos = self._infos(f"hashes={urllib.parse.quote(torrent_hash)}")
        return infos[0] if infos else None

    def delete(self, torrent_hash: str, delete_files: bool = True) -> None:
        self._call("/api/v2/torrents/delete", {"hashes": torrent_hash, "deleteFiles": "true" if delete_files else "false"})
```

- [ ] **Step 5 : Vérifier** — `.venv/bin/pytest tests/test_store_prowlarr.py tests/test_store_qbittorrent.py -q` → verts ; suite complète verte.

- [ ] **Step 6 : Commit**

```bash
git add bookmallow/store/providers/prowlarr.py bookmallow/store/qbittorrent.py tests/test_store_prowlarr.py tests/test_store_qbittorrent.py
git commit -m "feat(store): Prowlarr provider and qBittorrent WebUI client

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6 : Recherche unifiée et cache (`store/search.py`)

**Files:**
- Create: `bookmallow/store/search.py`
- Test: `tests/test_store_search.py`

**Interfaces:**
- Consumes: T3 `librivox.search/plan`, T4 `archive.search/plan`, T5 `prowlarr.search`, T2 models, T1 `Config`.
- Produces: `MAX_RESULTS = 60`, `PROWLARR_GATE_TIMEOUT = 10.0` ; `class SearchCache(ttl=600.0, max_entries=200, clock=time.monotonic)` avec `get(q, lang) -> tuple[list[SearchResult], dict[str, str]] | None`, `put(q, lang, results, providers) -> None`, `lookup(key) -> SearchResult | None` ; `unified_search(q, lang, config, cache, *, librivox_search=librivox.search, archive_search=archive.search, prowlarr_search=prowlarr.search) -> tuple[list[SearchResult], dict[str, str]]` (statuts `"ok"|"error"|"busy"|"disabled"`) ; `resolve_result(source, source_id, config, *, librivox_plan=librivox.plan, archive_plan=archive.plan) -> SearchResult | None` (None si source inconnue ou fournisseur désactivé ; `StoreError` propagée).

- [ ] **Step 1 : Tests**

`tests/test_store_search.py` :
```python
from __future__ import annotations

from dataclasses import replace

import pytest

from bookmallow.store import search as sx
from bookmallow.store.models import BookPlan, SearchResult, StoreError, Track


def R(source, sid, **kw):
    return SearchResult(source, sid, kw.pop("title", f"{source}-{sid}"), **kw)


def const(results):
    def fn(*args, **kwargs):
        return list(results)
    return fn


def boom(*args, **kwargs):
    raise StoreError("provider_error", "down")


@pytest.fixture
def tconfig(config):
    return replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q", store_timeout_s=2.0)


def test_merge_dedupes_archive_against_librivox_and_sorts_prowlarr(tconfig):
    libri = [R("librivox", "1", alt_ids=["ia_one"]), R("librivox", "2")]
    arch = [R("archive", "ia_one"), R("archive", "ia_two")]
    prow = [R("prowlarr", "a", seeders=3), R("prowlarr", "b", seeders=None), R("prowlarr", "c", seeders=9)]
    cache = sx.SearchCache()
    results, providers = sx.unified_search("q", "all", tconfig, cache, librivox_search=const(libri),
                                           archive_search=const(arch), prowlarr_search=const(prow))
    assert [r.key for r in results] == ["librivox:1", "librivox:2", "archive:ia_two", "prowlarr:c", "prowlarr:a", "prowlarr:b"]
    assert providers == {"librivox": "ok", "archive": "ok", "prowlarr": "ok"}
    assert cache.lookup("prowlarr:c").seeders == 9 and cache.lookup("nope:x") is None


def test_provider_failure_is_isolated_and_disabled_reported(config):
    c = replace(config, store_archive=False)
    results, providers = sx.unified_search("q", "fr", c, sx.SearchCache(), librivox_search=const([R("librivox", "1")]),
                                           archive_search=boom, prowlarr_search=boom)
    assert [r.key for r in results] == ["librivox:1"]
    assert providers == {"librivox": "ok", "archive": "disabled", "prowlarr": "disabled"}
    results, providers = sx.unified_search("q2", "fr", config, sx.SearchCache(), librivox_search=boom,
                                           archive_search=const([R("archive", "z")]), prowlarr_search=boom)
    assert [r.key for r in results] == ["archive:z"] and providers["librivox"] == "error"


def test_cache_hit_skips_providers_and_expires(tconfig):
    now = [1000.0]
    cache = sx.SearchCache(ttl=600, clock=lambda: now[0])
    calls = []

    def counting(*a, **k):
        calls.append(1)
        return [R("librivox", "1")]

    sx.unified_search("q", "all", tconfig, cache, librivox_search=counting, archive_search=const([]), prowlarr_search=const([]))
    sx.unified_search("q", "all", tconfig, cache, librivox_search=counting, archive_search=const([]), prowlarr_search=const([]))
    assert len(calls) == 1
    now[0] += 601
    sx.unified_search("q", "all", tconfig, cache, librivox_search=counting, archive_search=const([]), prowlarr_search=const([]))
    assert len(calls) == 2
    assert cache.get("q", "fr") is None  # different language = different entry


def test_cache_evicts_oldest(config):
    cache = sx.SearchCache(max_entries=2)
    for i in range(3):
        cache.put(f"q{i}", "all", [R("librivox", str(i))], {})
    assert cache.get("q0", "all") is None and cache.get("q2", "all") is not None


def test_results_capped(config):
    many = [R("archive", str(i)) for i in range(80)]
    results, _ = sx.unified_search("q", "all", config, sx.SearchCache(), librivox_search=const([]), archive_search=const(many),
                                   prowlarr_search=const([]))
    assert len(results) == sx.MAX_RESULTS


def test_prowlarr_gate_reports_busy(tconfig, monkeypatch):
    monkeypatch.setattr(sx, "PROWLARR_GATE_TIMEOUT", 0.01)
    sx._PROWLARR_GATE.acquire()
    try:
        _, providers = sx.unified_search("q", "all", tconfig, sx.SearchCache(), librivox_search=const([]),
                                         archive_search=const([]), prowlarr_search=const([R("prowlarr", "x")]))
    finally:
        sx._PROWLARR_GATE.release()
    assert providers["prowlarr"] == "busy"


def test_resolve_result(config):
    plan = BookPlan("Titre", "Auteur", "fr", 100, "https://c/x.jpg", [Track("u", 1.0, "c")])
    r = sx.resolve_result("librivox", "904", config, librivox_plan=lambda sid, timeout: plan, archive_plan=boom)
    assert r.key == "librivox:904" and r.title == "Titre" and r.author == "Auteur" and r.duration == 100 and r.cover == "https://c/x.jpg"
    assert sx.resolve_result("prowlarr", "x", config) is None
    assert sx.resolve_result("archive", "x", replace(config, store_archive=False), archive_plan=boom) is None
    with pytest.raises(StoreError):
        sx.resolve_result("archive", "x", config, archive_plan=boom)
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_search.py -q` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/store/search.py` :
```python
"""Unified search across providers with a short-lived cache (spec §6.1, §6.2)."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable

from ..config import Config
from .models import SearchResult, StoreError
from .providers import archive, librivox, prowlarr

log = logging.getLogger(__name__)
MAX_RESULTS = 60
PROWLARR_GATE_TIMEOUT = 10.0
_PROWLARR_GATE = threading.Semaphore(1)


class SearchCache:
    """(query, lang) → (results, provider statuses), kept `ttl` seconds, at most `max_entries` entries."""

    def __init__(self, ttl: float = 600.0, max_entries: int = 200, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._max, self._clock = ttl, max_entries, clock
        self._entries: "OrderedDict[tuple[str, str], tuple[float, list[SearchResult], dict[str, str]]]" = OrderedDict()
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, (ts, _, _) in self._entries.items() if now - ts > self._ttl]:
            del self._entries[key]
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def get(self, q: str, lang: str) -> tuple[list[SearchResult], dict[str, str]] | None:
        with self._lock:
            self._purge()
            hit = self._entries.get((q, lang))
            return (list(hit[1]), dict(hit[2])) if hit else None

    def put(self, q: str, lang: str, results: list[SearchResult], providers: dict[str, str]) -> None:
        with self._lock:
            self._entries[(q, lang)] = (self._clock(), list(results), dict(providers))
            self._entries.move_to_end((q, lang))
            self._purge()

    def lookup(self, key: str) -> SearchResult | None:
        with self._lock:
            self._purge()
            for _, results, _ in reversed(self._entries.values()):
                for r in results:
                    if r.key == key:
                        return r
        return None


def _gated_prowlarr(fn, q: str, config: Config) -> list[SearchResult]:
    if not _PROWLARR_GATE.acquire(timeout=PROWLARR_GATE_TIMEOUT):
        raise StoreError("busy", "another Prowlarr search is still running")
    try:
        return fn(q, config)
    finally:
        _PROWLARR_GATE.release()


def unified_search(q: str, lang: str, config: Config, cache: SearchCache, *,
                   librivox_search=librivox.search, archive_search=archive.search,
                   prowlarr_search=prowlarr.search) -> tuple[list[SearchResult], dict[str, str]]:
    cached = cache.get(q, lang)
    if cached is not None:
        return cached
    providers = {"librivox": "disabled", "archive": "disabled", "prowlarr": "disabled"}
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="store-search")
    futures = {}
    if config.store_librivox:
        futures["librivox"] = pool.submit(librivox_search, q, lang, timeout=config.store_timeout_s)
    if config.store_archive:
        futures["archive"] = pool.submit(archive_search, q, lang, timeout=config.store_timeout_s)
    if config.torrent_enabled:
        futures["prowlarr"] = pool.submit(_gated_prowlarr, prowlarr_search, q, config)
    done, _pending = wait(futures.values(), timeout=config.store_timeout_s + PROWLARR_GATE_TIMEOUT + 5)
    pool.shutdown(wait=False, cancel_futures=True)

    found: dict[str, list[SearchResult]] = {}
    for name, fut in futures.items():
        if fut not in done:
            providers[name] = "error"
            log.warning("store search: %s timed out", name)
            continue
        try:
            found[name] = list(fut.result())
            providers[name] = "ok"
        except StoreError as exc:
            providers[name] = "busy" if exc.code == "busy" else "error"
            log.warning("store search: %s failed [%s]: %s", name, exc.code, exc.detail)
        except Exception:  # noqa: BLE001 - one broken provider must not break the others
            providers[name] = "error"
            log.exception("store search: %s crashed", name)

    libri = found.get("librivox", [])
    seen_ia = {alt for r in libri for alt in r.alt_ids}
    arch = [r for r in found.get("archive", []) if r.source_id not in seen_ia]
    prow = sorted(found.get("prowlarr", []), key=lambda r: (r.seeders if r.seeders is not None else -1), reverse=True)
    merged = (libri + arch + prow)[:MAX_RESULTS]
    cache.put(q, lang, merged, providers)
    return merged, providers


def resolve_result(source: str, source_id: str, config: Config, *,
                   librivox_plan=librivox.plan, archive_plan=archive.plan) -> SearchResult | None:
    """Rebuild a SearchResult for a free-source book that fell out of the cache (spec §6.2)."""
    if source == "librivox" and config.store_enabled and config.store_librivox:
        plan = librivox_plan(source_id, timeout=config.store_timeout_s)
    elif source == "archive" and config.store_enabled and config.store_archive:
        plan = archive_plan(source_id, timeout=config.store_timeout_s)
    else:
        return None
    return SearchResult(source=source, source_id=source_id, title=plan.title, author=plan.author,
                        language=plan.language, duration=plan.duration, cover=plan.cover)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_store_search.py -q` → verts ; suite complète verte.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/store/search.py tests/test_store_search.py
git commit -m "feat(store): unified provider search with cache and result resolution

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7 : `procutil.py` (factorisation) et assembleur M4B (`store/assemble.py`)

**Files:**
- Create: `bookmallow/procutil.py`, `bookmallow/store/assemble.py`
- Modify: `bookmallow/converter.py` (remplacer les définitions locales par des imports)
- Test: `tests/test_store_assemble.py` (les tests `tests/test_converter.py` existants doivent rester verts sans modification)

**Interfaces:**
- Produces (`procutil.py`) : `escape_ffmetadata(value) -> str`, `class StderrTail(stream, keep=20)` (`.text()`), `terminate_process_groups(procs, grace) -> None`, `parse_progress_line(line) -> int | None`, `progress_percent(out_time_us, duration) -> float`, `unlink_quietly(path) -> None`, `close_quietly(*streams) -> None`.
- Produces (`assemble.py`) : `@dataclass AssembleRequest(tracks: list[Track], out_path: Path, work_dir: Path, title: str, author=None, language=None, duration=None, cover=None, bitrate="64k", copy_audio=False, source_url=None)` avec `part_path` ; `concat_list(tracks) -> str` ; `chapters_from_tracks(tracks) -> list[dict]` (`{"title","start","end"}` en secondes, `[]` si une durée manque) ; `ffmetadata(req) -> str` ; `ffmpeg_command(req, list_path, meta_path, cover_path) -> list[str]` ; `cover_filename(content_type) -> str | None` ; `class Assembly(req, on_progress=None, popen=subprocess.Popen, kill_grace=5.0, fetch_bytes=get_bytes)` avec `run()` (bloquant ; lève `converter.ConversionError`/`converter.Cancelled`) et `cancel()`.
- `converter.py` garde les noms `_Tail`, `_terminate`, `_unlink`, `_escape`, `parse_progress_line`, `progress_percent` (alias) pour les tests existants.

- [ ] **Step 1 : Tests**

`tests/test_store_assemble.py` :
```python
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from bookmallow import procutil
from bookmallow.converter import Cancelled, ConversionError
from bookmallow.store import assemble as asm
from bookmallow.store.models import StoreError, Track

TRACKS = [Track("https://archive.org/download/x/a%201.mp3", 10.0, "Un"), Track("https://archive.org/download/x/b's.mp3", 5.5, "Deux")]


def req(tmp_path, **kw):
    base = dict(tracks=list(TRACKS), out_path=tmp_path / "Livre [Auteur].m4b", work_dir=tmp_path / ".work" / "job1",
                title="Livre", author="Auteur", language="fr", duration=15, cover="https://c/cover.jpg", bitrate="64k")
    base.update(kw)
    return asm.AssembleRequest(**base)


class FakeProc:
    def __init__(self, cmd, stdout=b"", rc=0):
        self.cmd, self.stdout, self.stderr, self.rc, self.pid = cmd, io.BytesIO(stdout), io.BytesIO(b"err line\n"), rc, 4242

    def wait(self):
        return self.rc

    def poll(self):
        return self.rc


def fake_popen(progress=b"out_time_us=7500000\nprogress=end\n", rc=0, write=True):
    calls = []

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        if write:
            Path(cmd[-1]).write_bytes(b"m4b")
        return FakeProc(cmd, progress, rc)

    popen.calls = calls
    return popen


def ok_cover(url, timeout=10.0, max_bytes=5_000_000):
    return b"\xff\xd8jpeg", "image/jpeg"


def test_procutil_helpers(tmp_path):
    assert procutil.escape_ffmetadata("a=b;c#d\\e\nf") == "a\\=b\;c\\#d\\\\e\\\nf"
    assert procutil.parse_progress_line("out_time_us=1500000") == 1_500_000 and procutil.parse_progress_line("x") is None
    assert procutil.progress_percent(50_000_000, 100) == 50.0
    p = tmp_path / "gone"
    procutil.unlink_quietly(p)  # no error when missing
    s = io.BytesIO(b"x")
    procutil.close_quietly(s, None)
    assert s.closed


def test_concat_list_escapes_quotes():
    text = asm.concat_list(TRACKS)
    assert text.splitlines()[0] == "ffconcat version 1.0"
    assert "file 'https://archive.org/download/x/a%201.mp3'" in text
    assert "file 'https://archive.org/download/x/b'\\''s.mp3'" in text


def test_chapters_from_tracks():
    assert asm.chapters_from_tracks(TRACKS) == [{"title": "Un", "start": 0.0, "end": 10.0}, {"title": "Deux", "start": 10.0, "end": 15.5}]
    assert asm.chapters_from_tracks([Track("u", None, "x")]) == []
    assert asm.chapters_from_tracks([Track("u", 3.0, "")]) == [{"title": "Chapter 1", "start": 0.0, "end": 3.0}]


def test_ffmetadata_has_tags_and_chapters(tmp_path):
    text = asm.ffmetadata(req(tmp_path, title="A=B", source_url="https://librivox.org/x"))
    assert text.startswith(";FFMETADATA1\n") and "title=A\\=B" in text and "artist=Auteur" in text
    assert "album=A\\=B" in text and "genre=Audiobook" in text and "comment=https://librivox.org/x" in text
    assert text.count("[CHAPTER]") == 2 and "START=10000\nEND=15500\ntitle=Deux" in text


def test_ffmpeg_command_reencode_with_cover(tmp_path):
    r = req(tmp_path)
    cmd = asm.ffmpeg_command(r, tmp_path / "list.txt", tmp_path / "meta.ffm", tmp_path / "cover.jpg")
    assert cmd[0] == "ffmpeg" and cmd[cmd.index("-protocol_whitelist") + 1] == "file,http,https,tcp,tls,crypto"
    assert cmd[cmd.index("-f") + 1] == "concat" and "-safe" in cmd
    assert cmd.count("-i") == 3 and "-map_chapters" in cmd and "-disposition:v" in cmd and "attached_pic" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac" and cmd[cmd.index("-b:a") + 1] == "64k" and cmd[cmd.index("-ac") + 1] == "1"
    assert "+faststart" in cmd and cmd[-2:] == ["ipod", str(tmp_path / "Livre [Auteur].part.m4b")]
    assert cmd[cmd.index("-progress") + 1] == "pipe:1"


def test_ffmpeg_command_copy_without_cover(tmp_path):
    cmd = asm.ffmpeg_command(req(tmp_path, copy_audio=True, cover=None), tmp_path / "l", tmp_path / "m", None)
    assert cmd.count("-i") == 2 and cmd[cmd.index("-c:a") + 1] == "copy" and "-b:a" not in cmd and "attached_pic" not in cmd


def test_cover_filename():
    assert asm.cover_filename("image/jpeg") == "cover.jpg" and asm.cover_filename("image/png") == "cover.png"
    assert asm.cover_filename("text/html") is None


def test_run_success_downloads_cover_reports_progress_and_cleans_work_dir(tmp_path):
    popen = fake_popen()
    r = req(tmp_path)
    seen = []
    asm.Assembly(r, on_progress=seen.append, popen=popen, fetch_bytes=ok_cover).run()
    assert r.out_path.exists() and not r.part_path.exists()
    assert seen == [50.0]
    cmd, kw = popen.calls[0]
    assert kw["start_new_session"] is True and kw["stdout"] is subprocess.PIPE
    assert any(str(a).endswith("cover.jpg") for a in cmd) and any(str(a).endswith("list.txt") for a in cmd)
    assert not r.work_dir.exists()


def test_run_without_cover_when_download_fails(tmp_path):
    def bad_cover(url, timeout=10.0, max_bytes=5_000_000):
        raise StoreError("provider_error", "nope")
    popen = fake_popen()
    asm.Assembly(req(tmp_path), popen=popen, fetch_bytes=bad_cover).run()
    assert "attached_pic" not in popen.calls[0][0]


def test_run_uses_local_cover_path(tmp_path):
    local = tmp_path / "folder.jpg"
    local.write_bytes(b"jpg")
    popen = fake_popen()
    asm.Assembly(req(tmp_path, cover=str(local)), popen=popen, fetch_bytes=None).run()
    assert str(local) in popen.calls[0][0]


def test_run_failure_removes_part_and_keeps_tail(tmp_path):
    r = req(tmp_path)
    with pytest.raises(ConversionError) as exc:
        asm.Assembly(r, popen=fake_popen(rc=1), fetch_bytes=ok_cover).run()
    assert exc.value.code == "ffmpeg" and exc.value.detail == "err line" and "err line" in exc.value.tail
    assert not r.part_path.exists() and not r.out_path.exists() and not r.work_dir.exists()


def test_cancel_before_run(tmp_path):
    a = asm.Assembly(req(tmp_path), popen=fake_popen(), fetch_bytes=ok_cover, kill_grace=0.01)
    a.cancel()
    with pytest.raises(Cancelled):
        a.run()
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_assemble.py -q` → FAIL.

- [ ] **Step 3 : Créer `procutil.py`**

```python
"""Process helpers shared by the YouTube converter and the store assembler."""
from __future__ import annotations

import os
import re
import signal
import threading
import time
from collections import deque
from pathlib import Path

_ESCAPE = re.compile(r"([=;#\\\n])")


def escape_ffmetadata(value: str) -> str:
    return _ESCAPE.sub(r"\\\1", value)


class StderrTail(threading.Thread):
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


def terminate_process_groups(procs, grace: float) -> None:
    """SIGTERM every live process group, then SIGKILL whatever survives `grace` seconds."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = [p for p in procs if p.poll() is None]
        if not alive:
            return
        for proc in alive:
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except OSError:
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.05)


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


def unlink_quietly(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def close_quietly(*streams) -> None:
    for stream in streams:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
```

- [ ] **Step 4 : Alléger `converter.py`**

Remplacer les imports `import os, re, signal, threading, time`, `from collections import deque` et les définitions de `_ESCAPE`, `_escape`, `parse_progress_line`, `progress_percent`, `_Tail`, `_terminate`, `_unlink` par :
```python
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import QUALITIES
from .metadata import classify_error, last_line
from .procutil import (StderrTail as _Tail, close_quietly, escape_ffmetadata as _escape, parse_progress_line,  # noqa: F401
                       progress_percent, terminate_process_groups as _terminate, unlink_quietly as _unlink)
from .retention import part_path
```
et remplacer les trois `close()` du bloc `finally` par `close_quietly(ff.stdout, ff.stderr) if ff is not None else None` et `close_quietly(yt.stderr) if yt is not None else None` (ou deux `if`). Le reste du module est inchangé. Vérifier : `.venv/bin/pytest tests/test_converter.py -q` → 20 tests verts.

- [ ] **Step 5 : Créer `store/assemble.py`**

```python
"""Assemble chapter tracks (URLs or local files) into one M4B with chapters and cover art (spec §6.3, §6.4)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..converter import Cancelled, ConversionError
from ..metadata import last_line
from ..procutil import (StderrTail, close_quietly, escape_ffmetadata, parse_progress_line, progress_percent,
                        terminate_process_groups, unlink_quietly)
from ..retention import part_path
from .http import get_bytes
from .models import StoreError, Track

log = logging.getLogger(__name__)
PROTOCOLS = "file,http,https,tcp,tls,crypto"
_COVER_NAMES = {"image/jpeg": "cover.jpg", "image/jpg": "cover.jpg", "image/png": "cover.png"}


@dataclass
class AssembleRequest:
    tracks: list[Track]
    out_path: Path
    work_dir: Path
    title: str
    author: str | None = None
    language: str | None = None
    duration: int | None = None
    cover: str | None = None  # URL, or a local path when the cover came with a torrent
    bitrate: str = "64k"
    copy_audio: bool = False
    source_url: str | None = None

    @property
    def part_path(self) -> Path:
        return part_path(self.out_path)


def concat_list(tracks: list[Track]) -> str:
    lines = ["ffconcat version 1.0"]
    for t in tracks:
        lines.append("file '" + t.location.replace("'", "'\\''") + "'")
    return "\n".join(lines) + "\n"


def chapters_from_tracks(tracks: list[Track]) -> list[dict]:
    if not tracks or any(t.duration is None for t in tracks):
        return []
    chapters, start = [], 0.0
    for i, t in enumerate(tracks, 1):
        end = start + float(t.duration)
        chapters.append({"title": t.title or f"Chapter {i}", "start": start, "end": end})
        start = end
    return chapters


def ffmetadata(req: AssembleRequest) -> str:
    tags = {"title": req.title, "album": req.title, "genre": "Audiobook"}
    if req.author:
        tags["artist"] = req.author
        tags["album_artist"] = req.author
    if req.source_url:
        tags["comment"] = req.source_url
    lines = [";FFMETADATA1"] + [f"{k}={escape_ffmetadata(v)}" for k, v in tags.items()]
    for ch in chapters_from_tracks(req.tracks):
        start, end = int(round(ch["start"] * 1000)), int(round(ch["end"] * 1000))
        if end <= start:
            continue
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={escape_ffmetadata(ch['title'])}"]
    return "\n".join(lines) + "\n"


def ffmpeg_command(req: AssembleRequest, list_path: Path, meta_path: Path, cover_path: Path | None) -> list[str]:
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-protocol_whitelist", PROTOCOLS, "-f", "concat", "-safe", "0", "-i", str(list_path),
           "-i", str(meta_path)]
    if cover_path is not None:
        cmd += ["-i", str(cover_path)]
    cmd += ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
    if cover_path is not None:
        cmd += ["-map", "2:v", "-c:v", "copy", "-disposition:v", "attached_pic"]
    if req.copy_audio:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", req.bitrate, "-ac", "1"]
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-y", "-f", "ipod", str(req.part_path)]
    return cmd


def cover_filename(content_type: str | None) -> str | None:
    return _COVER_NAMES.get((content_type or "").lower())


class Assembly:
    """One ffmpeg run producing the final M4B. `run()` blocks; `cancel()` may be called from any thread."""

    def __init__(self, req: AssembleRequest, on_progress: Callable[[float], None] | None = None,
                 popen=subprocess.Popen, kill_grace: float = 5.0, fetch_bytes=get_bytes):
        self.req = req
        self._on_progress = on_progress or (lambda percent: None)
        self._popen = popen
        self._kill_grace = kill_grace
        self._fetch_bytes = fetch_bytes
        self._procs: list = []
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            procs = list(self._procs)
        terminate_process_groups(procs, self._kill_grace)

    def _cover_path(self, work: Path) -> Path | None:
        cover = self.req.cover
        if not cover:
            return None
        if "://" not in cover:
            local = Path(cover)
            return local if local.is_file() else None
        if self._fetch_bytes is None:
            return None
        try:
            body, ctype = self._fetch_bytes(cover, timeout=10.0)
        except StoreError as exc:
            log.warning("cover download failed (%s), continuing without cover", exc.detail)
            return None
        name = cover_filename(ctype) or ("cover.jpg" if body[:3] == b"\xff\xd8\xff" else None)
        if name is None:
            return None
        path = work / name
        path.write_bytes(body)
        return path

    def run(self) -> None:
        req = self.req
        work = req.work_dir
        work.mkdir(parents=True, exist_ok=True)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = None
        try:
            if self._cancelled.is_set():
                raise Cancelled()
            list_path, meta_path = work / "list.txt", work / "meta.ffm"
            list_path.write_text(concat_list(req.tracks), encoding="utf-8")
            meta_path.write_text(ffmetadata(req), encoding="utf-8")
            cover_path = self._cover_path(work)

            proc = self._popen(ffmpeg_command(req, list_path, meta_path, cover_path),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            with self._lock:
                self._procs = [proc]
            if self._cancelled.is_set():
                terminate_process_groups([proc], self._kill_grace)
            tail = StderrTail(proc.stderr)
            for raw in proc.stdout:
                us = parse_progress_line(raw.decode("utf-8", "replace"))
                if us is not None:
                    self._on_progress(progress_percent(us, req.duration))
            rc = proc.wait()
            tail.join(timeout=2)
            if self._cancelled.is_set():
                raise Cancelled()
            if rc != 0:
                text = tail.text()
                raise ConversionError("ffmpeg", last_line(text) or f"ffmpeg exited with {rc}", tail=text)
            os.replace(req.part_path, req.out_path)
        except BaseException:
            unlink_quietly(req.part_path)
            raise
        finally:
            if proc is not None:
                close_quietly(proc.stdout, proc.stderr)
            shutil.rmtree(work, ignore_errors=True)
```

- [ ] **Step 6 : Vérifier** — `.venv/bin/pytest tests/test_store_assemble.py tests/test_converter.py -q` → verts ; suite complète verte.

- [ ] **Step 7 : Commit**

```bash
git add bookmallow/procutil.py bookmallow/converter.py bookmallow/store/assemble.py tests/test_store_assemble.py
git commit -m "feat(store): shared process helpers and M4B assembler with chapters and cover

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8 : Acquisition torrent (`store/torrent.py`)

**Files:**
- Create: `bookmallow/store/torrent.py`
- Test: `tests/test_store_torrent.py`

**Interfaces:**
- Consumes: T5 `QbtClient/TorrentInfo/QbtError`, T2 models, T1 `Config.path_map/qbt_category/torrent_stall_hours`, `converter.Cancelled`.
- Produces: `AUDIO_EXT`, `FINISHED_STATES`, `ERROR_STATES`, `natural_key(text) -> list`, `map_path(remote: str, path_map: tuple[str, str]) -> Path`, `list_audio_files(root: Path) -> list[Path]`, `ffprobe(path, run=subprocess.run) -> tuple[float | None, str | None]` (durée, codec), `class TorrentAcquisition(client, result, config, job_id, on_progress=None, *, sleep=time.sleep, clock=time.monotonic, prober=ffprobe, poll_interval=5.0, add_timeout=30.0)` avec attributs `hash: str | None`, `copy_audio: bool`, `single_file: Path | None` et méthodes `start() -> str`, `wait() -> TorrentInfo`, `plan(info) -> BookPlan`, `cleanup() -> None`, `cancel() -> None`.
- Progression : `on_progress(p)` avec `p` de 0 à 50 pendant le téléchargement (la file remonte 50–100 pour l'assemblage).

- [ ] **Step 1 : Tests**

`tests/test_store_torrent.py` :
```python
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bookmallow.converter import Cancelled
from bookmallow.store import torrent as tq
from bookmallow.store.models import SearchResult, StoreError
from bookmallow.store.qbittorrent import QbtError, TorrentInfo


def info(progress, state="downloading", downloaded=None, path="/downloads/bookmallow/Book"):
    return TorrentInfo("h1", "Book", progress, state, path, 1000, downloaded if downloaded is not None else int(progress * 1000))


class FakeClient:
    def __init__(self, infos, find_after=1):
        self.infos, self.find_after, self.calls, self.deleted = list(infos), find_after, [], []

    def login(self):
        self.calls.append("login")

    def ensure_category(self, name):
        self.calls.append(f"cat:{name}")

    def add(self, download, category, tags):
        self.calls.append(("add", download, category, tuple(tags)))

    def find_by_tag(self, tag):
        self.find_after -= 1
        return None if self.find_after >= 0 else info(0.0)

    def info(self, h):
        return self.infos.pop(0) if self.infos else None

    def delete(self, h, delete_files=True):
        self.deleted.append((h, delete_files))


RESULT = SearchResult("prowlarr", "abc", "Book Title", author="Idx", download="magnet:?xt=urn:btih:1", size_bytes=1000)


@pytest.fixture
def tconfig(config):
    return replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q", qbt_category="bookmallow",
                   qbt_path_map="/downloads:/incoming", torrent_stall_hours=1.0)


def make(client, tconfig, **kw):
    clock = kw.pop("clock", None) or Clock()
    return tq.TorrentAcquisition(client, RESULT, tconfig, "job1", kw.pop("on_progress", None), sleep=clock.sleep,
                                 clock=clock.now, prober=kw.pop("prober", lambda p: (10.0, "aac")), poll_interval=5.0, **kw), clock


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_natural_key_and_list_audio_files(tmp_path):
    assert sorted(["Ch 10.mp3", "Ch 2.mp3", "Ch 1.mp3"], key=tq.natural_key) == ["Ch 1.mp3", "Ch 2.mp3", "Ch 10.mp3"]
    (tmp_path / "disc2").mkdir()
    for name in ("disc2/03.mp3", "disc2/01.mp3", "02.mp3", "cover.jpg", "notes.txt", "10.M4A"):
        (tmp_path / name).write_bytes(b"x")
    assert [str(p.relative_to(tmp_path)) for p in tq.list_audio_files(tmp_path)] == ["02.mp3", "10.M4A", "disc2/01.mp3", "disc2/03.mp3"]
    single = tmp_path / "one.m4b"
    single.write_bytes(b"x")
    assert tq.list_audio_files(single) == [single] and tq.list_audio_files(tmp_path / "cover.jpg") == []


def test_map_path():
    assert tq.map_path("/downloads/bookmallow/Book", ("/downloads", "/incoming")) == Path("/incoming/bookmallow/Book")
    assert tq.map_path("/downloads", ("/downloads", "/incoming")) == Path("/incoming")
    assert tq.map_path("/elsewhere/x", ("/downloads", "/incoming")) == Path("/elsewhere/x")
    assert tq.map_path("/downloadsX/y", ("/downloads", "/incoming")) == Path("/downloadsX/y")


def test_ffprobe_parses_json_and_handles_failure(tmp_path):
    class Proc:
        returncode = 0
        stdout = '{"streams":[{"codec_name":"mp3"}],"format":{"duration":"12.5"}}'

    assert tq.ffprobe(tmp_path / "a.mp3", run=lambda *a, **k: Proc()) == (12.5, "mp3")

    class Bad:
        returncode = 1
        stdout = ""

    assert tq.ffprobe(tmp_path / "a.mp3", run=lambda *a, **k: Bad()) == (None, None)

    def boom(*a, **k):
        raise FileNotFoundError("ffprobe")

    assert tq.ffprobe(tmp_path / "a.mp3", run=boom) == (None, None)


def test_start_adds_and_finds_hash(tconfig):
    client = FakeClient([], find_after=2)
    acq, clock = make(client, tconfig)
    assert acq.start() == "h1" and acq.hash == "h1"
    assert client.calls[:2] == ["login", "cat:bookmallow"]
    assert client.calls[2] == ("add", "magnet:?xt=urn:btih:1", "bookmallow", ("bookmallow", "job-job1"))


def test_start_times_out_when_torrent_never_appears(tconfig):
    acq, clock = make(FakeClient([], find_after=10**6), tconfig, add_timeout=3.0)
    with pytest.raises(QbtError) as exc:
        acq.start()
    assert exc.value.code == "torrent_add"


def test_wait_reports_progress_then_finishes(tconfig):
    seen = []
    client = FakeClient([info(0.2), info(0.6), info(1.0, "uploading")])
    acq, clock = make(client, tconfig, on_progress=seen.append)
    acq.hash = "h1"
    done = acq.wait()
    assert done.progress == 1.0 and seen == [10.0, 30.0, 50.0]


def test_wait_error_state_and_vanished(tconfig):
    acq, _ = make(FakeClient([info(0.1, "error")]), tconfig)
    acq.hash = "h1"
    with pytest.raises(QbtError) as exc:
        acq.wait()
    assert exc.value.code == "torrent_error"
    acq, _ = make(FakeClient([]), tconfig)
    acq.hash = "h1"
    with pytest.raises(QbtError) as exc:
        acq.wait()
    assert exc.value.code == "torrent_error"


def test_wait_stalls_after_configured_hours(tconfig):
    client = FakeClient([info(0.1, downloaded=100)] * 1000)
    acq, clock = make(client, tconfig)  # stall after 1 h, poll every 5 s
    acq.hash = "h1"
    with pytest.raises(QbtError) as exc:
        acq.wait()
    assert exc.value.code == "torrent_stalled" and 3600 <= clock.t <= 3700
    assert client.deleted == []  # cleanup is the caller's job


def test_wait_cancel(tconfig):
    client = FakeClient([info(0.1), info(0.2)])
    acq, clock = make(client, tconfig)
    acq.hash = "h1"
    acq.cancel()
    with pytest.raises(Cancelled):
        acq.wait()


def test_plan_lists_tracks_probes_and_flags_copy(tconfig, tmp_path):
    root = tmp_path / "incoming" / "bookmallow" / "Book"
    root.mkdir(parents=True)
    for n in ("02 - two.m4a", "01 - one.m4a"):
        (root / n).write_bytes(b"x")
    cfg = replace(tconfig, qbt_path_map=f"/downloads:{tmp_path / 'incoming'}")
    probes = []

    def prober(p):
        probes.append(p.name)
        return (30.0, "aac")

    acq, _ = make(FakeClient([]), cfg, prober=prober)
    plan = acq.plan(info(1.0, "uploading", path="/downloads/bookmallow/Book"))
    assert [t.title for t in plan.tracks] == ["01 - one", "02 - two"] and probes == ["01 - one.m4a", "02 - two.m4a"]
    assert plan.tracks[0].location == str(root / "01 - one.m4a") and plan.duration == 60
    assert plan.title == "Book Title" and plan.author == "Idx" and acq.copy_audio is True and acq.single_file is None


def test_plan_mixed_codecs_single_m4b_and_no_audio(tconfig, tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    cfg = replace(tconfig, qbt_path_map=f"/dl:{root}")
    (root / "a.mp3").write_bytes(b"x")
    (root / "b.m4a").write_bytes(b"x")
    codecs = iter([(1.0, "mp3"), (None, "aac")])
    acq, _ = make(FakeClient([]), cfg, prober=lambda p: next(codecs))
    plan = acq.plan(info(1.0, "uploading", path="/dl"))
    assert acq.copy_audio is False and plan.duration == RESULT.duration
    single = root / "only.m4b"
    single.write_bytes(b"x")
    acq, _ = make(FakeClient([]), cfg, prober=lambda p: (5.0, "aac"))
    plan = acq.plan(info(1.0, "uploading", path="/dl/only.m4b"))
    assert acq.single_file == single and len(plan.tracks) == 1
    acq, _ = make(FakeClient([]), cfg)
    with pytest.raises(StoreError) as exc:
        acq.plan(info(1.0, "uploading", path="/dl/missing"))
    assert exc.value.code == "no_audio"


def test_cleanup_deletes_with_files_and_swallows_errors(tconfig):
    client = FakeClient([])
    acq, _ = make(client, tconfig)
    acq.cleanup()  # no hash yet → nothing
    acq.hash = "h1"
    acq.cleanup()
    assert client.deleted == [("h1", True)]

    class Angry(FakeClient):
        def delete(self, h, delete_files=True):
            raise QbtError("provider_error", "down")

    acq, _ = make(Angry([]), tconfig)
    acq.hash = "h1"
    acq.cleanup()  # logged, not raised
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_store_torrent.py -q` → FAIL.

- [ ] **Step 3 : Implémenter**

`bookmallow/store/torrent.py` :
```python
"""Acquire a book through qBittorrent and turn the finished files into a BookPlan (spec §6.4)."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from ..config import Config
from ..converter import Cancelled
from .models import BookPlan, SearchResult, StoreError, Track
from .qbittorrent import QbtClient, QbtError, TorrentInfo

log = logging.getLogger(__name__)
AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".flac", ".wma"}
FINISHED_STATES = {"uploading", "stalledUP", "queuedUP", "pausedUP", "stoppedUP", "forcedUP", "checkingUP"}
ERROR_STATES = {"error", "missingFiles"}
_NUM = re.compile(r"(\d+)")
Prober = Callable[[Path], tuple[float | None, str | None]]


def natural_key(text: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in _NUM.split(str(text))]


def map_path(remote: str, path_map: tuple[str, str]) -> Path:
    """Translate a path reported by qBittorrent into the path Bookmallow sees through its read-only mount."""
    src, dst = path_map
    if remote == src or remote.startswith(src.rstrip("/") + "/"):
        return Path(dst + remote[len(src):])
    return Path(remote)


def list_audio_files(root: Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in AUDIO_EXT else []
    if not root.is_dir():
        return []
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT]
    return sorted(files, key=lambda p: natural_key(str(p.relative_to(root))))


def ffprobe(path: Path, run=subprocess.run) -> tuple[float | None, str | None]:
    """(duration in seconds, audio codec name) via ffprobe; (None, None) when unavailable."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration:stream=codec_name",
           "-of", "json", str(path)]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if proc.returncode != 0:
        return None, None
    try:
        data = json.loads(proc.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        codec = (data.get("streams") or [{}])[0].get("codec_name")
        return (float(duration) if duration else None), (str(codec) if codec else None)
    except (ValueError, AttributeError, IndexError):
        return None, None


class TorrentAcquisition:
    """add → wait → plan → (assembly by the caller) → cleanup. `cancel()` may be called from any thread."""

    def __init__(self, client: QbtClient, result: SearchResult, config: Config, job_id: str,
                 on_progress: Callable[[float], None] | None = None, *, sleep=time.sleep, clock=time.monotonic,
                 prober: Prober = ffprobe, poll_interval: float = 5.0, add_timeout: float = 30.0):
        self.client, self.result, self.config, self.job_id = client, result, config, job_id
        self._on_progress = on_progress or (lambda p: None)
        self._sleep, self._clock, self._prober = sleep, clock, prober
        self._poll, self._add_timeout = poll_interval, add_timeout
        self._cancelled = threading.Event()
        self.hash: str | None = None
        self.copy_audio = False
        self.single_file: Path | None = None

    def cancel(self) -> None:
        self._cancelled.set()

    def start(self) -> str:
        if not self.result.download:
            raise QbtError("torrent_add", "this result has no download link")
        self.client.login()
        self.client.ensure_category(self.config.qbt_category)
        tag = f"job-{self.job_id}"
        self.client.add(self.result.download, self.config.qbt_category, ["bookmallow", tag])
        deadline = self._clock() + self._add_timeout
        while self._clock() < deadline:
            if self._cancelled.is_set():
                raise Cancelled()
            found = self.client.find_by_tag(tag)
            if found is not None:
                self.hash = found.hash
                return found.hash
            self._sleep(1.0)
        raise QbtError("torrent_add", "the torrent did not appear in qBittorrent")

    def wait(self) -> TorrentInfo:
        assert self.hash, "start() first"
        last_bytes, last_change = -1, self._clock()
        stall_after = self.config.torrent_stall_hours * 3600
        while True:
            if self._cancelled.is_set():
                raise Cancelled()
            info = self.client.info(self.hash)
            if info is None:
                raise QbtError("torrent_error", "the torrent vanished from qBittorrent")
            if info.state in ERROR_STATES:
                raise QbtError("torrent_error", f"qBittorrent state {info.state}")
            if info.progress >= 1.0 or info.state in FINISHED_STATES:
                self._on_progress(50.0)
                return info
            now = self._clock()
            if info.downloaded != last_bytes:
                last_bytes, last_change = info.downloaded, now
            elif now - last_change > stall_after:
                raise QbtError("torrent_stalled", f"no data for {self.config.torrent_stall_hours:g} h")
            self._on_progress(round(info.progress * 50, 1))
            self._sleep(self._poll)

    def plan(self, info: TorrentInfo) -> BookPlan:
        local = map_path(info.content_path, self.config.path_map)
        files = list_audio_files(local)
        if not files:
            raise StoreError("no_audio", f"no audio files under {local}")
        if len(files) == 1 and files[0].suffix.lower() == ".m4b":
            self.single_file = files[0]
        tracks, codecs = [], []
        for path in files:
            duration, codec = self._prober(path)
            codecs.append(codec)
            tracks.append(Track(location=str(path), duration=duration, title=path.stem))
        self.copy_audio = bool(codecs) and all(c == "aac" for c in codecs)
        duration = int(round(sum(t.duration for t in tracks))) if all(t.duration is not None for t in tracks) else self.result.duration
        return BookPlan(title=self.result.title, author=self.result.author, language=self.result.language,
                        duration=duration, cover=None, tracks=tracks)

    def cleanup(self) -> None:
        if not self.hash:
            return
        try:
            self.client.delete(self.hash, delete_files=True)
        except StoreError as exc:
            log.warning("could not delete torrent %s: %s", self.hash, exc.detail)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_store_torrent.py -q` → verts ; suite complète verte.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/store/torrent.py tests/test_store_torrent.py
git commit -m "feat(store): torrent acquisition through qBittorrent with stall detection and cleanup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9 : Intégration dans la file (`jobqueue.py`)

**Files:**
- Modify: `bookmallow/jobqueue.py`, `bookmallow/names.py`
- Test: `tests/test_jobqueue.py`, `tests/test_names.py`

**Interfaces:**
- Consumes: T1 (`Config.work_dir/book_bitrate/torrent_enabled/path_map`, `new_book_job`, `retention.part_path`), T3/T4 `plan()`, T5 `QbtClient`, T7 `AssembleRequest/Assembly`, T8 `TorrentAcquisition`, `converter.Cancelled/ConversionError`, `store.models.StoreError/SearchResult/BookPlan`.
- Produces (`names.py`) : `safe_tag(text: str | None, fallback: str, max_len: int = 40) -> str` (texte nettoyé des caractères interdits, tronqué ; `fallback` si vide).
- Produces (`jobqueue.py`) : `default_plan_for(source, source_id, config) -> BookPlan` ; `estimate_book_bytes(duration, size_bytes, bitrate) -> int` ; `JobQueue(..., plan_for=default_plan_for, assembly_factory=Assembly, torrent_factory=TorrentAcquisition, qbt_client_factory=QbtClient)` ; `submit_book(result: SearchResult, quality: str | None = None) -> Job` (lève `DuplicateJob`) ; `_process` route `kind == "book"` vers `_process_book` ; `recover()` nettoie les torrents orphelins, échoue les jobs Prowlarr encore en file (lien perdu) et vide `work_dir` ; `_progress` accepte `FETCHING` pour les jobs livre ; `cancel()` fonctionne pour toute étape (l'objet courant expose `cancel()`).
- Progression livre : source libre 0–100 % pendant l'assemblage ; torrent 0–50 % téléchargement, 50–100 % assemblage. Nom de fichier : `safe_filename(title, safe_tag(author, source_id), ext=".m4b")` → `Titre [Auteur].m4b`.

- [ ] **Step 1 : Tests**

Ajouter à `tests/test_names.py` :
```python
from bookmallow.names import safe_tag


def test_safe_tag():
    assert safe_tag("Guy de Maupassant", "x") == "Guy de Maupassant"
    assert safe_tag('A/B:C*"D', "x") == "ABCD"
    assert safe_tag("   ", "fallback") == "fallback" and safe_tag(None, "f") == "f"
    assert len(safe_tag("a" * 100, "x")) == 40
```

Ajouter à `tests/test_jobqueue.py` (après les helpers existants) :
```python
import shutil
from dataclasses import replace

from bookmallow.store.models import BookPlan, SearchResult, StoreError, Track
from bookmallow.store.qbittorrent import TorrentInfo

LIBRI = SearchResult("librivox", "904", "Boule de suif", author="Guy de Maupassant", language="fr", duration=1000,
                     cover="https://c/x.jpg", url="https://librivox.org/x")
TORR = SearchResult("prowlarr", "abc", "Dune", author="Idx", language="en", size_bytes=5000, download="magnet:?xt=1", url="https://idx/t")
PLAN = BookPlan("Boule de suif", "Guy de Maupassant", "fr", 1000, "https://c/x.jpg", [Track("https://a/1.mp3", 500.0, "Un"), Track("https://a/2.mp3", 500.0, "Deux")])


class FakeAssembly:
    instances: list["FakeAssembly"] = []
    behaviour = "ok"

    def __init__(self, req, on_progress=None):
        self.req, self.on_progress, self.cancelled = req, on_progress or (lambda p: None), False
        FakeAssembly.instances.append(self)

    def run(self):
        self.on_progress(50.0)
        if FakeAssembly.behaviour == "fail":
            raise ConversionError("ffmpeg", "boom", tail="l1\nl2")
        if self.cancelled:
            raise Cancelled()
        self.req.out_path.write_bytes(b"m4b" * 100)

    def cancel(self):
        self.cancelled = True


class FakeTorrent:
    instances: list["FakeTorrent"] = []
    behaviour = "ok"  # ok | single | stall | cancel_in_wait
    single_path: Path | None = None

    def __init__(self, client, result, config, job_id, on_progress=None, **kw):
        self.client, self.result, self.config, self.job_id = client, result, config, job_id
        self.on_progress = on_progress or (lambda p: None)
        self.hash, self.cleaned, self.cancelled = None, False, False
        self.copy_audio, self.single_file = True, None
        FakeTorrent.instances.append(self)

    def start(self):
        self.hash = "h1"
        return "h1"

    def wait(self):
        self.on_progress(25.0)
        if FakeTorrent.behaviour == "stall":
            from bookmallow.store.qbittorrent import QbtError
            raise QbtError("torrent_stalled", "no data")
        if FakeTorrent.behaviour == "cancel_in_wait" or self.cancelled:
            raise Cancelled()
        return TorrentInfo("h1", "Dune", 1.0, "uploading", "/downloads/bookmallow/Dune", 5000, 5000)

    def plan(self, info):
        if FakeTorrent.behaviour == "single":
            self.single_file = FakeTorrent.single_path
        return BookPlan("Dune", "Idx", "en", 3600, None, [Track("/incoming/bookmallow/Dune/01.m4a", 3600.0, "01")])

    def cleanup(self):
        self.cleaned = True

    def cancel(self):
        self.cancelled = True


class FakeQbt:
    created: list["FakeQbt"] = []

    def __init__(self, url, user, password, timeout=20.0):
        self.url, self.deleted, self.logged = url, [], False
        FakeQbt.created.append(self)

    def login(self):
        self.logged = True

    def delete(self, h, delete_files=True):
        self.deleted.append((h, delete_files))


@pytest.fixture
def bq(config):
    """A queue with book fakes; torrent configured."""
    FakeAssembly.instances, FakeTorrent.instances, FakeQbt.created = [], [], []
    FakeAssembly.behaviour, FakeTorrent.behaviour = "ok", "ok"
    cfg = replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    queue = jq.JobQueue(cfg, StateStore(cfg.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11), plan_for=lambda s, sid, c: PLAN,
                        assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    return queue


def test_estimate_book_bytes():
    assert jq.estimate_book_bytes(3600, None, "64k") == int(3600 * 64 * 1000 / 8 * 1.1)
    assert jq.estimate_book_bytes(None, 5000, "64k") == 5500
    assert jq.estimate_book_bytes(None, None, "64k") == 0


def test_submit_book_dedupes_on_key(bq):
    job = bq.submit_book(LIBRI)
    assert job.kind == "book" and job.video_id == "librivox:904" and job.quality == "64"
    with pytest.raises(jq.DuplicateJob):
        bq.submit_book(LIBRI)


def test_free_book_flow(bq):
    job = bq.submit_book(LIBRI)
    assert bq.process_next(block=False)
    job = bq.get(job.id)
    assert job.status is Status.DONE and job.filename == "Boule de suif [Guy de Maupassant].m4b" and job.progress == 100.0
    assert (bq.config.data_dir / job.filename).exists() and job.size_bytes == 300
    req = FakeAssembly.instances[0].req
    assert req.work_dir == bq.config.work_dir / job.id and req.cover == "https://c/x.jpg" and req.bitrate == "64k"
    assert req.copy_audio is False and req.source_url == "https://librivox.org/x" and len(req.tracks) == 2
    assert FakeTorrent.instances == []


def test_free_book_plan_error(bq):
    bq._plan_for = lambda s, sid, c: (_ for _ in ()).throw(StoreError("not_found", "gone"))
    job = bq.submit_book(LIBRI)
    bq.process_next(block=False)
    assert bq.get(job.id).status is Status.FAILED and bq.get(job.id).error_code == "not_found"


def test_torrent_book_flow_scales_progress_and_cleans_up(bq):
    seen = []
    job = bq.submit_book(TORR)
    orig = bq._progress
    bq._progress = lambda j, p: (seen.append(p), orig(j, p))
    bq.process_next(block=False)
    job = bq.get(job.id)
    assert job.status is Status.DONE and job.torrent_hash == "h1" and job.filename == "Dune [Idx].m4b"
    assert seen == [25.0, 75.0]  # wait → 25 ; assembly 50 → 50 + 50/2
    acq = FakeTorrent.instances[0]
    assert acq.cleaned is True and FakeQbt.created[0].url == "http://q"
    req = FakeAssembly.instances[0].req
    assert req.copy_audio is True and req.cover is None and req.tracks[0].location.startswith("/incoming")


def test_torrent_single_m4b_is_copied_not_assembled(bq, tmp_path):
    src = tmp_path / "src.m4b"
    src.write_bytes(b"ready")
    FakeTorrent.behaviour, FakeTorrent.single_path = "single", src
    job = bq.submit_book(TORR)
    bq.process_next(block=False)
    job = bq.get(job.id)
    assert job.status is Status.DONE and (bq.config.data_dir / job.filename).read_bytes() == b"ready"
    assert FakeAssembly.instances == [] and FakeTorrent.instances[0].cleaned


def test_torrent_stall_fails_and_cleans(bq):
    FakeTorrent.behaviour = "stall"
    job = bq.submit_book(TORR)
    bq.process_next(block=False)
    assert bq.get(job.id).error_code == "torrent_stalled" and FakeTorrent.instances[0].cleaned


def test_torrent_disabled_fails_cleanly(config):
    queue = jq.JobQueue(config, StateStore(config.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**12, 0, 10**11), plan_for=lambda s, sid, c: PLAN,
                        assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    job = queue.submit_book(TORR)
    queue.process_next(block=False)
    assert queue.get(job.id).error_code == "store_disabled"


def test_cancel_during_torrent_wait(bq):
    job = bq.submit_book(TORR)

    class CancellingTorrent(FakeTorrent):
        def wait(self):
            bq.cancel(job.id)
            return super().wait()

    bq._torrent_factory = CancellingTorrent
    bq.process_next(block=False)
    assert bq.get(job.id).status is Status.CANCELLED and FakeTorrent.instances[0].cancelled and FakeTorrent.instances[0].cleaned
    assert not list(bq.config.data_dir.glob("*.m4b"))


def test_book_disk_guard_uses_size(config):
    cfg = replace(config, min_free_mb=1, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    queue = jq.JobQueue(cfg, StateStore(cfg.state_path), fetch_video=meta_for, conversion_factory=FakeConversion,
                        disk_usage=lambda path: Usage(10**9, 0, 1_500_000), plan_for=lambda s, sid, c: BookPlan("T", None, None, None, None, [Track("u")]),
                        assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    big = replace(TORR, size_bytes=900_000)  # 990 000 needed, leaves 510 000 < 1 MB
    job = queue.submit_book(big)
    queue.process_next(block=False)
    assert queue.get(job.id).error_code == "no_space" and FakeTorrent.instances[-1].cleaned


def test_recover_cleans_orphan_torrent_and_queued_prowlarr(config):
    cfg = replace(config, prowlarr_url="http://p", prowlarr_api_key="k", qbt_url="http://q")
    store = StateStore(cfg.state_path)
    from bookmallow.jobs import new_book_job
    converting = new_book_job("prowlarr", "abc", "Dune", "Idx", "en", None, None, "64")
    converting.status, converting.torrent_hash = Status.CONVERTING, "h1"
    queued_t = new_book_job("prowlarr", "def", "Other", None, None, None, None, "64")
    queued_l = new_book_job("librivox", "1", "Libre", None, "fr", 10, None, "64")
    store.save([converting, queued_t, queued_l])
    (cfg.work_dir / "old").mkdir(parents=True)
    FakeQbt.created = []
    queue = jq.JobQueue(cfg, store, fetch_video=meta_for, conversion_factory=FakeConversion, disk_usage=lambda p: Usage(1, 0, 10**11),
                        plan_for=lambda s, sid, c: PLAN, assembly_factory=FakeAssembly, torrent_factory=FakeTorrent, qbt_client_factory=FakeQbt)
    queue.recover()
    assert queue.get(converting.id).status is Status.FAILED and FakeQbt.created[0].deleted == [("h1", True)]
    assert queue.get(queued_t.id).status is Status.FAILED and queue.get(queued_t.id).error_code == "interrupted"
    assert queue.get(queued_l.id).status is Status.QUEUED and not cfg.work_dir.exists()
    queue.process_next(block=False)
    assert queue.get(queued_l.id).status is Status.DONE


def test_youtube_flow_unchanged_with_book_fakes(bq):
    job = bq.submit(URL, "aaaaaaaaaaa", "64")
    bq.process_next(block=False)
    assert bq.get(job.id).status is Status.DONE and bq.get(job.id).kind == "youtube"
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_jobqueue.py tests/test_names.py -q` → FAIL.

- [ ] **Step 3 : `names.py`**

Ajouter :
```python
def safe_tag(text: str | None, fallback: str, max_len: int = 40) -> str:
    """Short bracket tag for file names (author, id): forbidden characters removed, truncated, `fallback` if empty."""
    cleaned = _SPACES.sub(" ", _FORBIDDEN.sub("", unicodedata.normalize("NFC", text or ""))).strip(" .")
    return cleaned[:max_len].rstrip(" .") or fallback
```

- [ ] **Step 4 : `jobqueue.py`**

Imports (compléter) :
```python
import shutil
from .jobs import Job, Status, new_book_job, new_job, now_iso
from .store.assemble import AssembleRequest, Assembly
from .store.models import BookPlan, SearchResult, StoreError
from .store.providers import archive, librivox
from .store.qbittorrent import QbtClient
from .store.torrent import TorrentAcquisition
```
Fonctions module :
```python
def default_plan_for(source: str, source_id: str, config: Config) -> BookPlan:
    if source == "librivox":
        return librivox.plan(source_id, timeout=config.store_timeout_s)
    if source == "archive":
        return archive.plan(source_id, timeout=config.store_timeout_s)
    raise StoreError("store_disabled", f"no plan provider for source {source!r}")


def estimate_book_bytes(duration: int | None, size_bytes: int | None, bitrate: str) -> int:
    kbps = int(bitrate.lower().rstrip("k") or 64)
    if duration:
        return int(duration * kbps * 1000 / 8 * 1.1)
    return int((size_bytes or 0) * 1.1)
```
`__init__` : signature étendue
```python
    def __init__(self, config: Config, store: StateStore, *,
                 fetch_video: Callable[[str], md.VideoMeta] = md.fetch_video,
                 conversion_factory=Conversion,
                 disk_usage=shutil.disk_usage,
                 plan_for=default_plan_for,
                 assembly_factory=Assembly,
                 torrent_factory=TorrentAcquisition,
                 qbt_client_factory=QbtClient):
```
et attributs `self._plan_for, self._assembly_factory, self._torrent_factory, self._qbt_client_factory`, `self._results: dict[str, SearchResult] = {}`, `self._current: object | None = None` (tout objet avec `cancel()`).

`recover()` — remplacer la première boucle par :
```python
            orphan_hashes: list[str] = []
            for job in self.jobs:
                if job.status in (Status.FETCHING, Status.CONVERTING):
                    job.status, job.error_code, job.error = Status.FAILED, "interrupted", "interrupted by a restart"
                    job.finished_at = now_iso()
                    if job.kind == "book" and job.torrent_hash:
                        orphan_hashes.append(job.torrent_hash)
                elif job.status is Status.QUEUED and job.kind == "book" and job.source == "prowlarr":
                    job.status, job.error_code, job.error = Status.FAILED, "interrupted", "download link lost after a restart"
                    job.finished_at = now_iso()
            for job in sorted((j for j in self.jobs if j.status is Status.QUEUED), key=lambda j: j.created_at):
                self._pending.put(job.id)
            for path in retention.remove_partials(self.config.data_dir):
                log.info("removed partial file %s", path.name)
            shutil.rmtree(self.config.work_dir, ignore_errors=True)
            for path in retention.prune(self.config.data_dir, self.config.max_files):
                log.info("retention: deleted %s", path.name)
            self._save()
        for torrent_hash in orphan_hashes:
            self._cleanup_orphan(torrent_hash)
```
plus :
```python
    def _cleanup_orphan(self, torrent_hash: str) -> None:
        if not self.config.torrent_enabled:
            return
        try:
            client = self._qbt_client_factory(self.config.qbt_url, self.config.qbt_user, self.config.qbt_password,
                                              timeout=self.config.store_timeout_s)
            client.login()
            client.delete(torrent_hash, delete_files=True)
            log.info("removed orphan torrent %s after restart", torrent_hash)
        except Exception as exc:  # noqa: BLE001 - best effort at startup
            log.warning("could not remove orphan torrent %s: %s", torrent_hash, exc)
```
`submit_book` :
```python
    def submit_book(self, result: SearchResult, quality: str | None = None) -> Job:
        quality = quality or self.config.default_quality
        with self._lock:
            for existing in self.jobs:
                if existing.video_id == result.key and existing.is_active:
                    raise DuplicateJob(existing)
            job = new_book_job(result.source, result.source_id, result.title, result.author, result.language,
                               result.duration, result.cover, quality)
            self._results[job.id] = result
            self.jobs.append(job)
            self._pending.put(job.id)
            self._save()
            return job
```
`_process` : insérer en tête
```python
        if job.kind == "book":
            self._process_book(job)
            return
```
`_process_book` et helpers :
```python
    def _process_book(self, job: Job) -> None:
        with self._lock:
            job.status, job.started_at = Status.FETCHING, now_iso()
            self._save()
        result = self._results.pop(job.id, None)
        acq = None
        try:
            if job.source == "prowlarr":
                if result is None or not result.download:
                    raise StoreError("interrupted", "download link lost after a restart")
                if not self.config.torrent_enabled:
                    raise StoreError("store_disabled", "torrent support is not configured")
                client = self._qbt_client_factory(self.config.qbt_url, self.config.qbt_user, self.config.qbt_password,
                                                  timeout=self.config.store_timeout_s)
                acq = self._torrent_factory(client, result, self.config, job.id, on_progress=lambda p: self._progress(job, p))
                with self._lock:
                    if job.status is Status.CANCELLED:
                        return
                    self._current, self._current_id = acq, job.id
                torrent_hash = acq.start()
                with self._lock:
                    job.torrent_hash = torrent_hash
                    self._save()
                plan = acq.plan(acq.wait())
                copy_audio, single_file, base, scale = acq.copy_audio, acq.single_file, 50.0, 0.5
            else:
                plan = self._plan_for(job.source, job.source_id, self.config)
                copy_audio, single_file, base, scale = False, None, 0.0, 1.0

            with self._lock:
                if job.status is Status.CANCELLED:
                    return
                job.title = plan.title or job.title
                job.author = plan.author or job.author
                job.language = plan.language or job.language
                job.duration = plan.duration or job.duration
                job.cover = job.cover or plan.cover
                job.thumbnail = job.cover
                reason = self._guard_book(job, result)
            if reason is not None:
                raise StoreError(*reason)

            out_path = self._book_target_path(job)
            if single_file is not None:
                self._copy_single(job, single_file, out_path)
            else:
                req = AssembleRequest(tracks=plan.tracks, out_path=out_path, work_dir=self.config.work_dir / job.id,
                                      title=job.title or "Audiobook", author=job.author, language=job.language,
                                      duration=job.duration, cover=None if job.source == "prowlarr" else plan.cover,
                                      bitrate=self.config.book_bitrate, copy_audio=copy_audio,
                                      source_url=result.url if result else None)
                asm = self._assembly_factory(req, on_progress=lambda p: self._progress(job, base + p * scale))
                with self._lock:
                    if job.status is Status.CANCELLED:
                        return
                    self._current, self._current_id = asm, job.id
                    job.status = Status.CONVERTING
                    self._save()
                asm.run()

            with self._lock:
                if job.status is Status.CANCELLED:
                    out_path.unlink(missing_ok=True)
                    self._save()
                    return
                job.filename = out_path.name
                job.size_bytes = out_path.stat().st_size if out_path.exists() else None
                job.progress = 100.0
                self._finish(job, Status.DONE)
                deleted = retention.prune(self.config.data_dir, self.config.max_files)
            for path in deleted:
                log.info("retention: deleted %s", path.name)
        except Cancelled:
            self._finish(job, Status.CANCELLED)
        except (StoreError, ConversionError) as exc:
            self._fail(job, exc.code, exc.detail, tail=getattr(exc, "tail", ""))
        finally:
            with self._lock:
                self._current, self._current_id = None, None
            if acq is not None:
                acq.cleanup()

    def _guard_book(self, job: Job, result: SearchResult | None) -> tuple[str, str] | None:
        hours = self.config.max_duration_hours
        if hours > 0 and job.duration and job.duration > hours * 3600:
            return "too_long", f"longer than {hours:g} h"
        need = estimate_book_bytes(job.duration, result.size_bytes if result else None, self.config.book_bitrate)
        free = self._disk_usage(str(self.config.data_dir)).free
        if free - need < self.config.min_free_mb * MB:
            return "no_space", f"about {need // MB} MB needed, {free // MB} MB free"
        return None

    def _book_target_path(self, job: Job):
        tag = names.safe_tag(job.author, job.source_id or "book")
        existing = {p.name for p in self.config.data_dir.iterdir()}
        return self.config.data_dir / names.unique_name(names.safe_filename(job.title, tag, ext=".m4b"), existing)

    def _copy_single(self, job: Job, src, out_path) -> None:
        """A torrent that already is one M4B: copy it as-is, no re-encoding."""
        with self._lock:
            if job.status is Status.CANCELLED:
                return
            job.status = Status.CONVERTING
            self._save()
        part = retention.part_path(out_path)
        shutil.copyfile(src, part)
        os.replace(part, out_path)
```
(`import os` en tête.) `_progress` :
```python
    def _progress(self, job: Job, percent: float) -> None:
        with self._lock:
            if job.status is Status.CONVERTING or (job.kind == "book" and job.status is Status.FETCHING):
                job.progress = round(percent, 1)
```
`cancel()` reste tel quel (l'objet courant peut être une `Conversion`, une `Assembly` ou une `TorrentAcquisition`). Note pour `test_book_disk_guard_uses_size` : le garde-fou s'exécute après `acq.plan()`, donc `acq.cleanup()` est appelé dans le `finally` — c'est le comportement attendu (les fichiers torrent sont supprimés quand le job échoue).

- [ ] **Step 5 : Vérifier** — `.venv/bin/pytest tests/test_jobqueue.py tests/test_names.py -q` → verts ; suite complète verte.

- [ ] **Step 6 : Commit**

```bash
git add bookmallow/jobqueue.py bookmallow/names.py tests/test_jobqueue.py tests/test_names.py
git commit -m "feat(store): book jobs in the queue (free and torrent flows, recovery, guards)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10 : Routes API du magasin (`app.py`)

**Files:**
- Modify: `bookmallow/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: T6 `SearchCache/unified_search/resolve_result`, T9 `JobQueue.submit_book`, T2 `providers_available/StoreError`.
- Produces: `create_app(config=None, jobqueue=None, start_worker=True, fetch_playlist=md.fetch_playlist, store_search=unified_search, store_resolve=resolve_result)` ; `build_state()` gagne `store: {"enabled": bool, "providers": {...}}` ; routes `GET /api/store/search`, `POST /api/store/jobs` (spec §7) ; CSP `img-src` étendu à `https://archive.org https://*.archive.org https://librivox.org https://*.librivox.org` ; avertissement au démarrage si configuration torrent partielle ; `app.extensions["store_cache"]`.
- Contrat `POST /api/store/jobs` : corps `{"key": "<source>:<id>"}` ou `{"source", "source_id"}`, `quality?` ; 201 `{jobs: [job]}` ; 400 `{error: "bad_request"|"bad_quality"|"store_disabled"}` ; 404 `{error: "not_found"}` ; 409 `{error: "duplicate", jobs}` ; 502 `{error: "provider_error", detail}`.

- [ ] **Step 1 : Tests**

Ajouter à `tests/test_app.py` :
```python
from bookmallow.store.models import SearchResult, StoreError

LIBRI = SearchResult("librivox", "904", "Boule de suif", author="Guy de Maupassant", language="fr", duration=1000, cover="https://c/x.jpg")
TORR = SearchResult("prowlarr", "abc", "Dune", seeders=5, size_bytes=10, download="magnet:?xt=1")


def store_client(config, results=(LIBRI, TORR), providers=None, resolve=None):
    calls = []

    def fake_search(q, lang, cfg, cache, **kw):
        calls.append((q, lang))
        res = list(results)
        cache.put(q, lang, res, providers or {"librivox": "ok", "archive": "ok", "prowlarr": "disabled"})
        return res, providers or {"librivox": "ok", "archive": "ok", "prowlarr": "disabled"}

    q = JobQueue(config, StateStore(config.state_path), fetch_video=lambda u: None, conversion_factory=None)
    q.recover()
    app = create_app(config, jobqueue=q, start_worker=False, store_search=fake_search,
                     store_resolve=resolve or (lambda source, source_id, cfg: None))
    app.config["TESTING"] = True
    c = app.test_client()
    c.queue, c.calls = q, calls
    return c


def test_store_search_ok_and_hides_download(config):
    c = store_client(config)
    r = c.get("/api/store/search?q=boule&lang=fr")
    assert r.status_code == 200
    d = r.get_json()
    assert c.calls == [("boule", "fr")]
    assert [x["key"] for x in d["results"]] == ["librivox:904", "prowlarr:abc"]
    assert "download" not in d["results"][1] and d["results"][1]["seeders"] == 5
    assert d["providers"]["prowlarr"] == "disabled"


@pytest.mark.parametrize("query", ["q=a", "q=" + "x" * 101, "lang=fr", "q=ok&lang=de"])
def test_store_search_validation(config, query):
    assert store_client(config).get(f"/api/store/search?{query}").status_code == 400


def test_store_search_default_lang_all_and_strip(config):
    c = store_client(config)
    assert c.get("/api/store/search?q=%20boule%20").status_code == 200 and c.calls == [("boule", "all")]


def test_store_disabled_routes(config):
    c = store_client(replace(config, store_enabled=False))
    assert c.get("/api/store/search?q=boule").status_code == 503
    assert c.post("/api/store/jobs", json={"key": "librivox:904"}).status_code == 503
    assert c.get("/api/state").get_json()["store"]["enabled"] is False


def test_store_state_block(config):
    d = store_client(config).get("/api/state").get_json()
    assert d["store"] == {"enabled": True, "providers": {"librivox": "enabled", "archive": "enabled", "prowlarr": "disabled"}}


def test_store_submit_from_cache_then_duplicate(config):
    c = store_client(config)
    c.get("/api/store/search?q=boule")
    r = c.post("/api/store/jobs", json={"key": "librivox:904", "quality": "128"})
    assert r.status_code == 201
    job = r.get_json()["jobs"][0]
    assert job["kind"] == "book" and job["source"] == "librivox" and job["quality"] == "128" and job["author"] == "Guy de Maupassant"
    assert c.queue.get(job["id"]) is not None
    r = c.post("/api/store/jobs", json={"source": "librivox", "source_id": "904"})
    assert r.status_code == 409 and r.get_json()["error"] == "duplicate"


def test_store_submit_resolves_when_not_cached(config):
    c = store_client(config, resolve=lambda source, sid, cfg: LIBRI if (source, sid) == ("librivox", "904") else None)
    assert c.post("/api/store/jobs", json={"key": "librivox:904"}).status_code == 201
    assert c.post("/api/store/jobs", json={"key": "prowlarr:zzz"}).status_code == 404


def test_store_submit_errors(config):
    def resolver(source, sid, cfg):
        raise StoreError("provider_error", "down")
    c = store_client(config, resolve=resolver)
    assert c.post("/api/store/jobs", json={"key": "nokey"}).status_code == 400
    assert c.post("/api/store/jobs", json={"key": "librivox:1", "quality": "320"}).status_code == 400
    assert c.post("/api/store/jobs", data="x", content_type="text/plain").status_code == 400
    r = c.post("/api/store/jobs", json={"key": "librivox:1"})
    assert r.status_code == 502 and r.get_json()["error"] == "provider_error"


def test_store_submit_prowlarr_needs_torrent_config(config):
    c = store_client(config)
    c.get("/api/store/search?q=dune")
    r = c.post("/api/store/jobs", json={"key": "prowlarr:abc"})
    assert r.status_code == 400 and r.get_json()["error"] == "store_disabled"


def test_csp_allows_archive_and_librivox_covers(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "https://*.archive.org" in csp and "https://*.librivox.org" in csp and "https://*.ytimg.com" in csp
```

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_app.py -q` → FAIL sur les nouveaux tests.

- [ ] **Step 3 : Implémenter**

Imports à ajouter dans `app.py` :
```python
from .store import providers_available
from .store.models import StoreError
from .store.search import SearchCache, resolve_result, unified_search
```
`build_state` : ajouter au dict renvoyé
```python
        "store": {"enabled": config.store_enabled, "providers": providers_available(config)},
```
Nouvelle fonction module :
```python
STORE_LANGS = ("fr", "en", "all")


def _store_submit(config: Config, q: JobQueue, cache: SearchCache, store_resolve):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="bad_request", detail="body must be JSON"), 400
    quality = str(data.get("quality") or config.default_quality)
    if quality not in QUALITIES:
        return jsonify(error="bad_quality"), 400
    key = str(data.get("key") or "")
    if not key and data.get("source") and data.get("source_id"):
        key = f"{data['source']}:{data['source_id']}"
    source, sep, source_id = key.partition(":")
    if not sep or not source or not source_id:
        return jsonify(error="bad_request", detail="key must be <source>:<id>"), 400
    result = cache.lookup(key)
    if result is None:
        try:
            result = store_resolve(source, source_id, config)
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 502
            return jsonify(error=exc.code if status == 404 else "provider_error", detail=exc.detail), status
    if result is None:
        return jsonify(error="not_found"), 404
    if result.source == "prowlarr" and not config.torrent_enabled:
        return jsonify(error="store_disabled"), 400
    try:
        job = q.submit_book(result, quality)
    except DuplicateJob as exc:
        return jsonify(error="duplicate", jobs=[exc.job.to_dict()]), 409
    return jsonify(jobs=[job.to_dict()]), 201
```
Dans `create_app` : signature `def create_app(config=None, jobqueue=None, start_worker=True, fetch_playlist=md.fetch_playlist, store_search=unified_search, store_resolve=resolve_result)` ; après la création de la file :
```python
    cache = SearchCache()
    app.extensions["store_cache"] = cache
    if config.torrent_config_state == "partial":
        log.warning("torrent support stays disabled: set PROWLARR_URL, PROWLARR_API_KEY and QBT_URL together")
```
CSP :
```python
            "default-src 'self'; img-src 'self' data: https://*.ytimg.com https://*.ggpht.com "
            "https://archive.org https://*.archive.org https://librivox.org https://*.librivox.org; "
            "frame-ancestors 'none'"
```
Routes :
```python
    @app.get("/api/store/search")
    @login_required
    def api_store_search():
        if not config.store_enabled or all(v != "enabled" for v in providers_available(config).values()):
            return jsonify(error="store_disabled"), 503
        q_text = (request.args.get("q") or "").strip()
        lang = request.args.get("lang") or "all"
        if not 2 <= len(q_text) <= 100 or lang not in STORE_LANGS:
            return jsonify(error="bad_request"), 400
        results, providers = store_search(q_text, lang, config, cache)
        return jsonify(results=[r.public() for r in results], providers=providers)

    @app.post("/api/store/jobs")
    @login_required
    def api_store_submit():
        if not config.store_enabled:
            return jsonify(error="store_disabled"), 503
        return _store_submit(config, q, cache, store_resolve)
```

- [ ] **Step 4 : Vérifier** — `.venv/bin/pytest tests/test_app.py -q` → verts ; suite complète verte.

- [ ] **Step 5 : Commit**

```bash
git add bookmallow/app.py tests/test_app.py
git commit -m "feat(store): search and submit API, store state, CSP for cover hosts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11 : Interface — onglets, recherche, cartes livre

**Files:**
- Modify: `bookmallow/templates/index.html`, `bookmallow/static/app.js`, `bookmallow/static/style.css`
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `GET /api/state` (`store.enabled`, `store.providers`, `jobs[*].kind/source/author/cover`, `files[*].kind/author`), `GET /api/store/search`, `POST /api/store/jobs` (T10).
- Produces: onglets `#tab-convert` / `#tab-store` (mémorisés dans `localStorage` `bookmallow.tab`), panneaux `#panel-convert` / `#panel-store`, formulaire `#store-form` (`#store-q`, pastilles `#store-langs`, `#store-btn`), `#store-msg`, `#store-providers`, `#store-results` ; nouvelles clés I18N (parité FR/EN) ; cartes de job et de fichier adaptées au `kind == "book"`.

- [ ] **Step 1 : Tests**

Modifier `tests/test_frontend.py` : dans `test_index_has_hooks_and_static_assets`, étendre la liste des hooks avec `'id="tab-convert"', 'id="tab-store"', 'id="panel-convert"', 'id="panel-store"', 'id="store-form"', 'id="store-q"', 'id="store-langs"', 'id="store-results"', 'data-store-enabled="1"'`. Ajouter :
```python
def test_store_tab_hidden_when_disabled(config):
    from dataclasses import replace
    html = client(replace(config, store_enabled=False)).get("/").get_data(as_text=True)
    assert 'data-store-enabled="0"' in html


def test_i18n_has_store_keys():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for key in ("tab_convert", "tab_store", "store_search", "store_add", "store_free", "store_torrent", "e_torrent_stalled",
                "e_qbt_auth", "e_no_audio", "status_book_fetching_torrent", "status_book_converting", "file_book"):
        assert f"\n      {key}:" in js, key
```
(`test_i18n_has_both_languages_with_same_keys` garantit la parité ; garder l'indentation 4/6 espaces.)

- [ ] **Step 2 : Vérifier l'échec** — `.venv/bin/pytest tests/test_frontend.py -q` → FAIL.

- [ ] **Step 3 : `index.html`**

Sur `<body>`, ajouter l'attribut `data-store-enabled="{{ 1 if config.store_enabled else 0 }}"`. Remplacer la section `<section class="card hero">…</section>` par :
```html
    <section class="card hero">
      <div class="tabs" role="tablist" aria-label="Bookmallow">
        <button id="tab-convert" class="tab active" type="button" role="tab" aria-selected="true" aria-controls="panel-convert" data-i18n="tab_convert"></button>
        <button id="tab-store" class="tab" type="button" role="tab" aria-selected="false" aria-controls="panel-store" data-i18n="tab_store"></button>
      </div>

      <div id="panel-convert" class="panel" role="tabpanel">
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
      </div>

      <div id="panel-store" class="panel hidden" role="tabpanel">
        <h1 data-i18n="store_title"></h1>
        <p class="lead" data-i18n="store_lead"></p>
        <form id="store-form" novalidate>
          <label class="sr-only" for="store-q" data-i18n="store_q_label"></label>
          <div class="url-row">
            <input id="store-q" name="q" type="search" autocomplete="off" spellcheck="false" minlength="2" maxlength="100" required>
            <button id="store-btn" class="btn primary" type="submit"><span data-i18n="store_search"></span> 🔍</button>
          </div>
          <fieldset class="qualities" id="store-langs">
            <legend data-i18n="store_lang"></legend>
          </fieldset>
        </form>
        <p id="store-msg" class="form-msg" role="status" aria-live="polite"></p>
        <p id="store-providers" class="note hidden"></p>
        <ul id="store-results" class="results"></ul>
      </div>
    </section>
```

- [ ] **Step 4 : `style.css`** — ajouter à la fin, avant le bloc `@media (max-width: 560px)` :
```css
/* tabs */
.tabs { display: flex; gap: 8px; margin: -6px 0 16px; }
.tab { font: inherit; font-weight: 800; font-size: .95rem; padding: 9px 16px; border-radius: 999px; border: 2px solid var(--pink); background: #fff; color: var(--plum); cursor: pointer; }
.tab.active { background: var(--pink-strong); border-color: var(--pink-strong); color: #fff; box-shadow: 0 8px 20px rgba(231, 90, 140, .25); }
.tab:focus-visible { outline: 3px solid var(--lilac); outline-offset: 2px; }
.panel.hidden { display: none; }

/* store results */
.results { list-style: none; margin: 16px 0 0; padding: 0; display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.result { display: grid; grid-template-columns: 72px 1fr; gap: 12px; padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: #fff; align-items: start; }
.result .thumb { width: 72px; height: 96px; }
.result .thumb img { object-fit: cover; }
.result-body { min-width: 0; display: grid; gap: 6px; }
.badge.free { background: var(--mint-soft); color: #23795A; }
.badge.torrent { background: var(--lilac-soft); color: #5B3FA6; }
.badge.book { background: var(--pink-soft); color: var(--pink-strong); }
.result-meta { color: var(--muted); font-size: .82rem; display: flex; flex-wrap: wrap; gap: 4px 10px; }
```
et dans le bloc `@media (max-width: 560px)` : `.results { grid-template-columns: 1fr; }`.

- [ ] **Step 5 : `app.js`**

(a) Clés I18N à ajouter dans **les deux** blocs, avant `hours: "h", minutes: "min",` :

FR :
```js
      tab_convert: "✨ Convertir",
      tab_store: "📚 Magasin",
      store_title: "Trouve ton prochain livre 📚",
      store_lead: "Cherche un titre ou un auteur : livres libres (LibriVox, Internet Archive) et, si c'est activé, tes indexeurs.",
      store_q_label: "Titre ou auteur",
      store_search: "Chercher",
      store_lang: "Langue",
      store_lang_fr: "Français",
      store_lang_en: "English",
      store_lang_all: "Toutes",
      store_hint: "Tape au moins deux lettres.",
      store_searching: "Recherche en cours…",
      store_none: "Aucun livre trouvé. Essaie un autre mot, ou l'autre langue.",
      store_add: "Ajouter à la file",
      store_added: "Livre ajouté à la file 📚",
      store_free: "Libre",
      store_torrent: "Torrent",
      store_seeders: "{n} sources",
      store_provider_down: "Source indisponible : {names}",
      store_provider_busy: "Prowlarr est occupé, réessaie dans un instant",
      store_disabled: "Le magasin n'est pas activé sur ce serveur.",
      store_duplicate: "Ce livre est déjà dans la file.",
      store_not_found: "Livre introuvable, relance la recherche.",
      status_book_fetching_free: "Préparation du livre…",
      status_book_fetching_torrent: "Téléchargement du torrent…",
      status_book_converting: "Assemblage du M4B…",
      file_book: "Livre",
      e_store_disabled: "Cette source n'est pas activée sur ce serveur",
      e_not_found: "Livre introuvable",
      e_provider_error: "La source ne répond pas",
      e_no_tracks: "Aucune piste audio trouvée",
      e_no_audio: "Aucune piste audio trouvée",
      e_torrent_add: "qBittorrent a refusé le torrent",
      e_torrent_error: "Erreur de téléchargement du torrent",
      e_torrent_stalled: "Torrent sans source, abandonné",
      e_qbt_auth: "Connexion à qBittorrent refusée",
      e_busy: "Source occupée, réessaie",
```
EN :
```js
      tab_convert: "✨ Convert",
      tab_store: "📚 Store",
      store_title: "Find your next book 📚",
      store_lead: "Search a title or an author: free books (LibriVox, Internet Archive) and, when enabled, your indexers.",
      store_q_label: "Title or author",
      store_search: "Search",
      store_lang: "Language",
      store_lang_fr: "Français",
      store_lang_en: "English",
      store_lang_all: "All",
      store_hint: "Type at least two letters.",
      store_searching: "Searching…",
      store_none: "No book found. Try another word, or the other language.",
      store_add: "Add to queue",
      store_added: "Book added to the queue 📚",
      store_free: "Free",
      store_torrent: "Torrent",
      store_seeders: "{n} seeders",
      store_provider_down: "Source unavailable: {names}",
      store_provider_busy: "Prowlarr is busy, try again in a moment",
      store_disabled: "The store is not enabled on this server.",
      store_duplicate: "This book is already queued.",
      store_not_found: "Book not found, search again.",
      status_book_fetching_free: "Preparing the book…",
      status_book_fetching_torrent: "Downloading the torrent…",
      status_book_converting: "Assembling the M4B…",
      file_book: "Book",
      e_store_disabled: "This source is not enabled on this server",
      e_not_found: "Book not found",
      e_provider_error: "The source is not answering",
      e_no_tracks: "No audio track found",
      e_no_audio: "No audio track found",
      e_torrent_add: "qBittorrent refused the torrent",
      e_torrent_error: "Torrent download error",
      e_torrent_stalled: "Torrent without seeders, abandoned",
      e_qbt_auth: "qBittorrent login refused",
      e_busy: "Source busy, try again",
```

(b) Dans `state`, ajouter :
```js
    tab: store.get("bookmallow.tab") || "convert",
    storeLang: store.get("bookmallow.storeLang") || body.dataset.defaultLang || "all",
    storeEnabled: body.dataset.storeEnabled === "1",
    storeResults: [],
```
et après `if (!I18N[state.lang]) state.lang = "fr";` : `if (!["fr", "en", "all"].includes(state.storeLang)) state.storeLang = "all";` puis `if (!state.storeEnabled) state.tab = "convert";`.

(c) Nouvelles fonctions (placer après `renderQualities`) :
```js
  function setTab(name) {
    state.tab = state.storeEnabled && name === "store" ? "store" : "convert";
    store.set("bookmallow.tab", state.tab);
    for (const n of ["convert", "store"]) {
      const active = n === state.tab;
      $(`#tab-${n}`).classList.toggle("active", active);
      $(`#tab-${n}`).setAttribute("aria-selected", String(active));
      $(`#panel-${n}`).classList.toggle("hidden", !active);
    }
    $("#tab-store").classList.toggle("hidden", !state.storeEnabled);
  }

  function renderStoreLangs() {
    const box = $("#store-langs");
    box.querySelectorAll(".quality").forEach((n) => n.remove());
    for (const l of ["fr", "en", "all"]) {
      const id = `sl-${l}`;
      const input = el("input", { type: "radio", name: "store-lang", id, value: l, onchange: () => { state.storeLang = l; store.set("bookmallow.storeLang", l); } });
      if (l === state.storeLang) input.checked = true;
      box.append(el("div", { class: "quality" }, [input, el("label", { for: id }, [el("b", { text: t(`store_lang_${l}`) })])]));
    }
  }

  function setStoreMsg(text, kind = "") {
    const node = $("#store-msg");
    node.textContent = text;
    node.className = `form-msg ${kind}`;
  }

  function resultCard(r) {
    const meta = [];
    if (r.author) meta.push(el("span", { text: r.author }));
    if (r.duration) meta.push(el("span", { text: fmtDuration(r.duration) }));
    if (r.size_bytes) meta.push(el("span", { text: fmtSize(r.size_bytes) }));
    if (r.language) meta.push(el("span", { text: r.language.toUpperCase() }));
    const free = r.source !== "prowlarr";
    const badge = el("span", { class: `badge ${free ? "free" : "torrent"}`, text: free ? t("store_free") : `${t("store_torrent")} · ${t("store_seeders", { n: r.seeders ?? 0 })}` });
    const actions = el("div", { class: "item-actions" }, [badge,
      el("button", { class: "btn primary small", type: "button", text: t("store_add"), onclick: (e) => addBook(r.key, e.currentTarget) })]);
    if (r.url) actions.append(el("a", { class: "btn ghost small", href: r.url, target: "_blank", rel: "noopener", text: "↗" }));
    const cover = free ? thumb(r.cover, "📚") : thumb(null, "🧲");
    return el("li", { class: "result", "data-key": r.key }, [cover, el("div", { class: "result-body" }, [
      el("div", { class: "item-title", text: r.title }), el("div", { class: "result-meta" }, meta), actions])]);
  }

  function renderStoreResults(results, providers) {
    state.storeResults = results;
    $("#store-results").replaceChildren(...results.map(resultCard));
    const down = Object.entries(providers || {}).filter(([, v]) => v === "error").map(([k]) => k);
    const busy = Object.values(providers || {}).includes("busy");
    const note = $("#store-providers");
    note.textContent = busy ? t("store_provider_busy") : (down.length ? t("store_provider_down", { names: down.join(", ") }) : "");
    note.classList.toggle("hidden", !note.textContent);
    setStoreMsg(results.length ? "" : t("store_none"));
  }

  async function storeSearch() {
    const q = $("#store-q").value.trim();
    if (q.length < 2) { setStoreMsg(t("store_hint"), "error"); return; }
    const btn = $("#store-btn");
    btn.disabled = true;
    setStoreMsg(t("store_searching"));
    try {
      const { status, payload } = await api(`/api/store/search?q=${encodeURIComponent(q)}&lang=${encodeURIComponent(state.storeLang)}`);
      if (status === 200) renderStoreResults(payload.results, payload.providers);
      else if (status === 503) setStoreMsg(t("store_disabled"), "error");
      else setStoreMsg(t("e_internal"), "error");
    } catch (err) {
      if (err.network) setStoreMsg(t("err_network"), "error");
    } finally {
      btn.disabled = false;
    }
  }

  async function addBook(key, button) {
    if (button) button.disabled = true;
    try {
      const { status, payload } = await api("/api/store/jobs", { method: "POST", body: JSON.stringify({ key, quality: state.quality }) });
      if (status === 201) { toast(t("store_added"), "ok"); refresh(); }
      else if (status === 409) toast(t("store_duplicate"), "error");
      else if (status === 404) toast(t("store_not_found"), "error");
      else if (status === 400 && payload.error === "store_disabled") toast(t("e_store_disabled"), "error");
      else if (status === 502) toast(t("e_provider_error"), "error");
      else toast(t("e_internal"), "error");
    } catch (err) {
      if (err.network) toast(t("err_network"), "error");
    } finally {
      if (button) button.disabled = false;
    }
  }
```
Modifier `thumb` pour accepter une icône de repli : `function thumb(url, fallback = "🎧") { … else box.textContent = fallback; … }`.

(d) `jobCard` : remplacer les premières lignes (jusqu'à `bodyParts`) par
```js
    const isBook = job.kind === "book";
    const meta = [];
    if (isBook && job.author) meta.push(el("span", { text: job.author }));
    if (!isBook && job.channel) meta.push(el("span", { text: job.channel }));
    if (job.duration) meta.push(el("span", { text: fmtDuration(job.duration) }));
    if (isBook) meta.push(el("span", { text: job.source === "prowlarr" ? t("store_torrent") : t("store_free") }));
    else meta.push(el("span", { text: t(`q${job.quality}`) }));
    const statusLabel = !isBook ? null
      : job.status === "fetching" ? t(job.source === "prowlarr" ? "status_book_fetching_torrent" : "status_book_fetching_free")
      : job.status === "converting" ? t("status_book_converting") : null;
    const bodyParts = [
      el("div", { class: "item-title", text: job.title || job.url }),
      el("div", { class: "item-meta" }, meta),
      el("div", { class: "item-actions" }, [statusPill(job.status, statusLabel)]),
    ];
```
et adapter `statusPill(status, label)` : `document.createTextNode(label || t(\`status_${status}\`))`. Dans la branche progression, remplacer `if (job.status === "converting") {` par `if (job.status === "converting" || (isBook && job.status === "fetching" && job.progress > 0)) {` et le `else if` suivant reste pour `fetching`/`queued` sans progression. Le `thumb(job.thumbnail)` de la dernière ligne devient `thumb(job.thumbnail, isBook ? "📚" : "🎧")`.

(e) `fileCard` : après `if (file.channel) …`, ajouter `if (file.author) meta.push(el("span", { text: file.author }));` ; dans `actions`, si `file.kind === "book"` ajouter en premier `el("span", { class: "badge book", text: t("file_book") })` ; `thumb(file.thumbnail, file.kind === "book" ? "📚" : "🎧")`.

(f) `render(data)` : en tête, `state.storeEnabled = !!(data.store && data.store.enabled); setTab(state.tab);`.

(g) `applyI18n()` : appeler `renderStoreLangs()` après `renderQualities()` et, si `state.storeResults.length`, `renderStoreResults(state.storeResults, {})`.

(h) Câblage (section `wiring`) :
```js
  $("#tab-convert").addEventListener("click", () => setTab("convert"));
  $("#tab-store").addEventListener("click", () => setTab("store"));
  $("#store-form").addEventListener("submit", (e) => { e.preventDefault(); storeSearch(); });
```
et avant `applyI18n();` final : `setTab(state.tab);`.

- [ ] **Step 6 : Vérifier** — `.venv/bin/pytest tests/test_frontend.py -q` → verts ; suite complète verte. Vérification de syntaxe JS dans l'image existante : `docker run --rm -v "$PWD/bookmallow/static/app.js:/app.js:ro" bookmallow:dev deno eval "new Function(await Deno.readTextFile('/app.js')); console.log('app.js parses OK')"` (l'entrypoint affiche une ligne de log avant ; c'est normal).

- [ ] **Step 7 : Commit**

```bash
git add bookmallow/templates/index.html bookmallow/static/app.js bookmallow/static/style.css tests/test_frontend.py
git commit -m "feat(store): store tab with unified search, result cards and book-aware queue/library

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12 : Version 1.1.0, documentation, déploiement chez Clem, test de bout en bout, tag

**Files:**
- Modify: `bookmallow/__init__.py`, `CHANGELOG.md`, `README.md`, `docker-compose.yml`, `docs/superpowers/specs/2026-09-23-bookmallow-design.md` (une ligne dans « Écarts »), `/home/clem/bookmallow-stack/docker-compose.yml`, `/home/clem/bookmallow-stack/.env`
- Create: `docs/screenshot-store.png`

- [ ] **Step 1 : Version et changelog**

`bookmallow/__init__.py` : `__version__ = "1.1.0"`. `CHANGELOG.md`, en tête :
```markdown
## 1.1.0 — 2026-09-24

- **Store tab**: search audiobooks on LibriVox and Internet Archive (FR/EN filters) and, when configured, through Prowlarr + qBittorrent.
- Books are assembled into a single chaptered **M4B** with cover art; free sources stream straight into ffmpeg (no intermediate files).
- Torrent downloads are removed from qBittorrent once assembled; stalled torrents are abandoned after `TORRENT_STALL_HOURS`.
- Shared retention: MP3s and M4Bs count together toward `MAX_FILES`.
- New variables: `STORE_ENABLED`, `STORE_LIBRIVOX`, `STORE_ARCHIVE`, `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBT_URL`, `QBT_USER`, `QBT_PASSWORD`, `QBT_CATEGORY`, `QBT_PATH_MAP`, `TORRENT_STALL_HOURS`, `BOOK_BITRATE`, `STORE_TIMEOUT_S`.
```

- [ ] **Step 2 : README (FR puis EN, même contenu)** — après la section « Configuration », ajouter :

FR :
```markdown
### 📚 Magasin de livres audio (v1.1)

Le second onglet cherche des livres audio et les livre en **un seul fichier M4B** (chapitres, couverture), lisible par les apps de livres audio du téléphone.

- **Sources libres, activées par défaut** : [LibriVox](https://librivox.org) et [Internet Archive](https://archive.org) (domaine public, lecteurs bénévoles, anglais très fourni, classiques français). Les chapitres sont lus en streaming par ffmpeg : aucun fichier intermédiaire.
- **Tes indexeurs, en option** : si tu utilises déjà Prowlarr et qBittorrent, renseigne `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBT_URL`, `QBT_USER`, `QBT_PASSWORD`, monte le dossier de téléchargement de qBittorrent en lecture seule sur `/incoming` et place Bookmallow sur le même réseau Docker. Les résultats apparaissent avec un badge « Torrent » ; une fois le livre assemblé, le torrent et ses fichiers sont supprimés de qBittorrent. Ce que tu télécharges par cette voie relève de ta responsabilité.
- Les livres suivent la **même rétention** que les MP3 : `MAX_FILES` compte tout.

| Variable | Défaut | Rôle |
|---|---|---|
| `STORE_ENABLED` | `1` | `0` masque l'onglet |
| `STORE_LIBRIVOX` / `STORE_ARCHIVE` | `1` | Sources libres |
| `PROWLARR_URL` / `PROWLARR_API_KEY` | vide | Prowlarr (ex. `http://prowlarr:9696`) |
| `QBT_URL` / `QBT_USER` / `QBT_PASSWORD` | vide | qBittorrent WebUI (ex. `http://qbittorrent:8080`) |
| `QBT_CATEGORY` | `bookmallow` | Catégorie qBittorrent utilisée (créée si absente) |
| `QBT_PATH_MAP` | `/downloads:/incoming` | Chemin vu par qBittorrent : chemin vu par Bookmallow |
| `TORRENT_STALL_HOURS` | `12` | Abandon d'un torrent sans progression |
| `BOOK_BITRATE` | `64k` | Débit AAC du M4B |
| `STORE_TIMEOUT_S` | `20` | Délai des appels aux sources |

Exemple compose avec le volet torrent :

```yaml
services:
  bookmallow:
    image: ghcr.io/clemdepernet/bookmallow:latest
    ports: ["7843:5000"]
    volumes:
      - ./data:/data
      - /chemin/vers/downloads/qbittorrent:/incoming:ro
    environment:
      - PROWLARR_URL=http://prowlarr:9696
      - PROWLARR_API_KEY=${PROWLARR_API_KEY}
      - QBT_URL=http://qbittorrent:8080
      - QBT_USER=${QBT_USER}
      - QBT_PASSWORD=${QBT_PASSWORD}
    networks: [medianet]
networks:
  medianet:
    external: true
    name: media-stack_medianet
```
```
EN (même structure) :
```markdown
### 📚 Audiobook store (v1.1)

The second tab searches audiobooks and delivers each one as **a single M4B file** (chapters, cover art) that phone audiobook apps understand.

- **Free sources, on by default**: [LibriVox](https://librivox.org) and [Internet Archive](https://archive.org) (public domain, volunteer readers, huge English catalogue, French classics). Chapters are streamed straight into ffmpeg: no intermediate files.
- **Your indexers, optional**: if you already run Prowlarr and qBittorrent, set `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBT_URL`, `QBT_USER`, `QBT_PASSWORD`, mount qBittorrent's download folder read-only at `/incoming` and put Bookmallow on the same Docker network. Results show a "Torrent" badge; once a book is assembled, the torrent and its files are removed from qBittorrent. What you download this way is your responsibility.
- Books follow the **same retention** as MP3s: `MAX_FILES` counts everything.

| Variable | Default | Purpose |
|---|---|---|
| `STORE_ENABLED` | `1` | `0` hides the tab |
| `STORE_LIBRIVOX` / `STORE_ARCHIVE` | `1` | Free sources |
| `PROWLARR_URL` / `PROWLARR_API_KEY` | empty | Prowlarr (e.g. `http://prowlarr:9696`) |
| `QBT_URL` / `QBT_USER` / `QBT_PASSWORD` | empty | qBittorrent WebUI (e.g. `http://qbittorrent:8080`) |
| `QBT_CATEGORY` | `bookmallow` | qBittorrent category (created if missing) |
| `QBT_PATH_MAP` | `/downloads:/incoming` | Path as seen by qBittorrent : path as seen by Bookmallow |
| `TORRENT_STALL_HOURS` | `12` | Give up on a torrent without progress |
| `BOOK_BITRATE` | `64k` | AAC bitrate of the M4B |
| `STORE_TIMEOUT_S` | `20` | Timeout for source calls |
```
(plus le même exemple compose). Ajouter la capture `<img src="docs/screenshot-store.png" width="720" alt="Bookmallow store tab">` sous le titre de section FR. Dans `docker-compose.yml` (racine), ajouter sous les variables commentées :
```yaml
      # ---- Magasin / Store (v1.1) ----
      # - STORE_ENABLED=1
      # - PROWLARR_URL=http://prowlarr:9696
      # - PROWLARR_API_KEY=
      # - QBT_URL=http://qbittorrent:8080
      # - QBT_USER=
      # - QBT_PASSWORD=
      # - QBT_PATH_MAP=/downloads:/incoming     # + volume: /path/to/qbittorrent/downloads:/incoming:ro
```
Dans la spec v1, section « Écarts », ajouter : `- v1.1 : la bibliothèque contient aussi des M4B (magasin) ; voir la spec 2026-09-24.`

- [ ] **Step 3 : Tests et commit**

`.venv/bin/pytest -q` (verts) puis :
```bash
git add bookmallow/__init__.py CHANGELOG.md README.md docker-compose.yml docs/superpowers/specs/2026-09-23-bookmallow-design.md docs/superpowers/plans/2026-09-24-bookmallow-store.md
git commit -m "docs: v1.1.0 store documentation, compose example and changelog

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 4 : Stack locale**

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
      - /mnt/ssd/jellyfin/media/downloads:/incoming:ro
    environment:
      - TZ=Asia/Kuala_Lumpur
      - PUID=1000
      - PGID=1000
      - MAX_FILES=6
      - DEFAULT_QUALITY=64
      - DEFAULT_LANG=fr
      - APP_PASSWORD=${APP_PASSWORD}
      - PROWLARR_URL=http://prowlarr:9696
      - PROWLARR_API_KEY=${PROWLARR_API_KEY}
      - QBT_URL=http://qbittorrent:8080
      - QBT_USER=${QBT_USER}
      - QBT_PASSWORD=${QBT_PASSWORD}
    networks:
      - medianet
    restart: unless-stopped

networks:
  medianet:
    external: true
    name: media-stack_medianet
```
`.env` : ajouter `PROWLARR_API_KEY=<valeur lue dans /home/clem/media-stack/prowlarr/config.xml, balise <ApiKey>>`, `QBT_USER=` et `QBT_PASSWORD=` avec les identifiants fournis par Clem (si absents, laisser vides : le volet torrent restera désactivé et l'interface le dira). Ne jamais afficher ces valeurs dans le rapport.
```bash
cd /home/clem/bookmallow-stack && docker compose config -q && docker compose up -d --build && sleep 25 && docker compose ps && curl -s http://127.0.0.1:7843/healthz && docker compose logs --tail 5 bookmallow
```
Vérifier dans les logs l'absence de l'avertissement « torrent support stays disabled » quand les trois variables sont renseignées.

- [ ] **Step 5 : Test de bout en bout**

Se connecter avec le mot de passe (`curl -c jar -d "password=$APP_PASSWORD" http://127.0.0.1:7843/login`), puis :
1. `GET /api/store/search?q=maupassant&lang=fr` → résultats LibriVox (badge libre) ; `q=austen&lang=en` → résultats anglais ; si Prowlarr est configuré, `q=dune&lang=all` doit contenir des résultats `source: prowlarr` (aucun téléchargement).
2. `POST /api/store/jobs {"key": "librivox:<id court FR>"}` (choisir un livre de moins de 30 min dans les résultats, par exemple une nouvelle de Maupassant) → suivre `/api/state` jusqu'à `done` ; vérifier avec `docker compose exec bookmallow ffprobe -v error -show_chapters -show_entries format_tags=title,artist -of json "/data/<fichier>.m4b"` que les chapitres et les tags sont présents et qu'une image est attachée (`-show_streams` → un flux `mjpeg`/`png` `attached_pic`).
3. Même chose avec un livre EN court d'Internet Archive (`source: archive`).
4. Torrent (seulement si qBittorrent est configuré) : utiliser un torrent d'Internet Archive pour tester la chaîne sans Prowlarr : dans le conteneur, `docker compose exec bookmallow python -c` avec un petit script qui crée `SearchResult("prowlarr","e2e","IA test",download="https://archive.org/download/<id>/<id>_archive.torrent",size_bytes=…)` puis `app.extensions["jobqueue"].submit_book(...)` n'est pas possible depuis un autre processus : à la place, prendre un vrai résultat Prowlarr de la recherche `dune` (ou tout livre de test choisi par Clem) via `POST /api/store/jobs {"key": "prowlarr:<id>"}` et observer : progression 0→50 pendant le téléchargement (qBittorrent montre le torrent en catégorie `bookmallow`), puis 50→100, puis M4B dans la bibliothèque et torrent disparu de qBittorrent. Si aucun torrent de test acceptable n'existe, documenter le test comme non exécuté.
5. Annulation : lancer un livre LibriVox long et l'annuler depuis l'interface → job `cancelled`, aucun `.part.m4b` ni dossier dans `/data/.work`.
6. Rétention : après ces essais, `ls data/` ne contient jamais plus de 6 fichiers audio.

- [ ] **Step 6 : Capture d'écran de l'onglet Magasin**

Avec des résultats affichés (recherche « maupassant », FR), capturer la page à 1280 px de large dans `docs/screenshot-store.png` (< 600 Ko) : depuis le Pi, `docker run --rm --network host --security-opt seccomp=unconfined -v "$PWD/docs":/out zenika/alpine-chrome:latest --no-sandbox --headless --disable-gpu --hide-scrollbars --virtual-time-budget=8000 --window-size=1280,1250 --screenshot=/out/screenshot-store.png http://192.168.1.56:7843/` ne verra que la page de connexion à cause du mot de passe : capturer plutôt en lançant temporairement l'app sans mot de passe sur un autre port (`docker run --rm -p 7845:5000 -e STORE_ENABLED=1 bookmallow:dev`, ouvrir l'onglet Magasin et chercher via la même page — le clic sur l'onglet et la saisie ne sont pas scriptables en headless : ajouter alors dans l'URL le paramètre `?tab=store&q=maupassant` que `app.js` lit au démarrage (ajout d'une lecture de `URLSearchParams` : si `tab`/`q` présents, `setTab(tab)`, remplir `#store-q`, lancer `storeSearch()`), commiter cette petite amélioration avec la capture.

- [ ] **Step 7 : Fusion, CI, tag**

```bash
cd /home/clem/bookmallow && git add docs/screenshot-store.png bookmallow/static/app.js && git commit -m "docs: store screenshot; deep link ?tab=store&q= for sharing searches

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git checkout main && git merge --ff-only feat/store && git push origin main
gh run watch --repo clemdepernet/bookmallow --exit-status $(gh run list --repo clemdepernet/bookmallow --workflow CI --limit 1 --json databaseId -q '.[0].databaseId')
git tag -a v1.1.0 -m "Bookmallow 1.1.0 — audiobook store" && git push origin v1.1.0
gh run watch --repo clemdepernet/bookmallow --exit-status $(gh run list --repo clemdepernet/bookmallow --workflow "Release image" --limit 1 --json databaseId -q '.[0].databaseId')
```
Puis `cd /home/clem/bookmallow-stack && docker compose up -d --build` pour être sur `main`.

---

## Self-review (fait à l'écriture du plan)

**Couverture de la spec v1.1** : §3/§4 modules → T2–T10 ; §5 modèle (Job, SearchResult, BookPlan) → T1, T2 ; §6.1 recherche → T3, T4, T5, T6, T10 ; §6.2 soumission (cache, re-résolution, 404/409/400) → T6, T10 ; §6.3 acquisition libre (concat URLs, M4B, chapitres, couverture, `.work`) → T7, T9 ; §6.4 torrent (add/poll/stall/path map/tri/ffprobe/copie/cleanup) → T5, T8, T9 ; §6.5 rétention M4B et `files.kind` → T1 ; §6.6 démarrage (`.work`, torrents orphelins) → T9 ; §7 API → T10 ; §8 config et déploiement → T1, T12 ; §9 interface → T11 ; §10 erreurs → codes dans T2–T9, libellés dans T11 ; §11 tests → chaque tâche ; §12 livraison → T12. Cache `(q, lang)` TTL 600 s et 200 entrées → T6 ; un appel Prowlarr à la fois → T6 ; `single_video`-like fallbacks non concernés.

**Cohérence des noms** : `SearchResult.key/public()/alt_ids` (T2) utilisés en T6/T10/T11 ; `librivox.search(q, lang, fetch, timeout, limit)` / `archive.search(...)` appelés en T6 avec `timeout=` ; `prowlarr.search(q, config)` appelé via `_gated_prowlarr` ; `plan(source_id, timeout=)` (T3/T4) appelé en T6 `resolve_result` et T9 `default_plan_for` ; `QbtClient(url, user, password, timeout=)` construit en T8 tests / T9 ; `TorrentAcquisition(client, result, config, job_id, on_progress=…)` (T8) construit en T9 ; `AssembleRequest` champs (T7) = ceux passés en T9 ; `Assembly(req, on_progress=)` ; `retention.part_path/list_audio/is_partial` (T1) utilisés en T7/T9/app ; `new_book_job(...)` (T1) utilisé en T9 ; `names.safe_tag` (T9) ; statuts fournisseurs `ok|error|busy|disabled` (T6) lus par T11 ; clés I18N `e_<code>` couvrent tous les codes de T2–T9 (`store_disabled, not_found, provider_error, no_tracks, no_audio, torrent_add, torrent_error, torrent_stalled, qbt_auth, busy, interrupted`).

**Points d'attention à l'exécution** : la regex `_RUNTIME` (T2) accepte `h:m:s`, `m:s` et `s(.frac)` ; le parseur Internet Archive `length` (T4) garde les décimales quand la valeur est un nombre ; `unified_search` (T6) ne referme pas les threads en retard (ils finissent seuls) ; `test_wait_stalls_after_configured_hours` (T8) boucle ~720 itérations avec l'horloge simulée, c'est voulu et rapide.
