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
