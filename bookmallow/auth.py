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
        # A GET on a download link is usually followed straight from a browser tab or an <a>
        # click, not from the app's own fetch() calls: send the person to a real login page
        # instead of a raw JSON error they cannot act on.
        if request.method == "GET" and request.path.startswith("/api/files/"):
            return redirect(url_for("login", next=request.path))
        if request.path.startswith("/api/"):
            return jsonify(error="unauthorized"), 401
        return redirect(url_for("login", next=request.path))
    return wrapped
