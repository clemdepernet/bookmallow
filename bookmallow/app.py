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
