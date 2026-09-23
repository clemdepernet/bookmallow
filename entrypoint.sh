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
