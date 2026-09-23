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
