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
