## 1.2.0 — 2026-09-25

- New identity: Bookmallow is an audiobook companion. "Find a book" is now the home tab; YouTube becomes "Import from YouTube".
- New visual direction: paper, ink, bordeaux and powder rose, serif headings, book-cover cards, underlined tabs; new open-book logo. Still no external fonts, scripts or styles.
- Copy rewritten in both languages; README repositioned around the library.

# Changelog

## 1.1.0 — 2026-09-24

- **Store tab**: search audiobooks on LibriVox and Internet Archive (FR/EN filters) and, when configured, through Prowlarr + qBittorrent.
- Books are assembled into a single chaptered **M4B** with cover art; free sources stream straight into ffmpeg (no intermediate files).
- Torrent downloads are removed from qBittorrent once assembled; stalled torrents are abandoned after `TORRENT_STALL_HOURS`.
- Shared retention: MP3s and M4Bs count together toward `MAX_FILES`.
- New variables: `STORE_ENABLED`, `STORE_LIBRIVOX`, `STORE_ARCHIVE`, `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBT_URL`, `QBT_USER`, `QBT_PASSWORD`, `QBT_CATEGORY`, `QBT_PATH_MAP`, `TORRENT_STALL_HOURS`, `BOOK_BITRATE`, `STORE_TIMEOUT_S`.

## 1.0.0 — 2026-09-23

First Bookmallow release, forked from TheFatPanda-Dev/youtube-to-mp3-docker.

- Streaming conversion (`yt-dlp -o - | ffmpeg`): only the final MP3 ever touches the disk.
- Single-worker queue with live progress, cancel, and recovery after a restart.
- Retention: keep the newest `MAX_FILES` (default 6), the UI warns and marks the next file to go.
- Audiobook-friendly default: 64 kbps mono (≈ 29 MB/hour), 128/192 kbps available.
- Optional shared password (`APP_PASSWORD`).
- Pastel FR/EN single-page UI, no external resources.
- Slim multi-arch image (amd64/arm64) with ffmpeg and deno, `PUID/PGID`, healthcheck.
