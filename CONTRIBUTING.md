# Contributing

Merci ! / Thanks!

- Run the tests: `python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest`
- Run the app locally: `DATA_DIR=./data .venv/bin/flask --app wsgi:app run --port 7843` (needs `yt-dlp`, `ffmpeg` and `deno` on your PATH for real conversions)
- Build the image with its tests: `docker build --target test .`
- Keep modules small and tested; the external tools (`yt-dlp`, `ffmpeg`) are always injected in tests, never executed.
- UI strings live in `bookmallow/static/app.js` (`I18N`), keep `fr` and `en` in sync.
