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
