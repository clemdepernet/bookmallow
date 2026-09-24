"""Opt-in end-to-end check of the M4B assembly with the real ffmpeg (skipped when ffmpeg/ffprobe are missing).

It runs in the Docker test stage, where ffmpeg is installed; on a host without ffmpeg it is skipped."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from bookmallow.store.assemble import AssembleRequest, Assembly
from bookmallow.store.models import Track

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg and ffprobe"),
]


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=60)


def test_real_ffmpeg_builds_chaptered_m4b_with_cover_and_progress(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    tracks = []
    for i, (freq, seconds) in enumerate(((440, 2), (660, 3)), 1):
        path = src / f"{i:02d}.wav"
        _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-ac", "1", str(path))
        tracks.append(Track(location=str(path), duration=float(seconds), title=f"Chapitre {i}"))
    cover = src / "cover.jpg"
    _ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(cover))

    out = tmp_path / "Livre [Auteur].m4b"
    req = AssembleRequest(tracks=tracks, out_path=out, work_dir=tmp_path / ".work" / "job", title="Livre",
                          author="Auteur", language="fr", duration=5, cover=str(cover), bitrate="64k")
    seen: list[float] = []
    Assembly(req, on_progress=seen.append, fetch_bytes=None).run()

    assert out.is_file() and not req.part_path.exists() and not req.cover_part_path.exists()
    assert not req.work_dir.exists()
    assert seen and seen[-1] >= 90.0, seen

    probe = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_streams", "-show_format", "-of", "json",
                            str(out)], capture_output=True, text=True, check=True, timeout=60)
    data = json.loads(probe.stdout)
    assert [c["tags"]["title"] for c in data["chapters"]] == ["Chapitre 1", "Chapitre 2"]
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    pics = [s for s in data["streams"] if s["codec_type"] == "video" and s.get("disposition", {}).get("attached_pic") == 1]
    assert len(audio) == 1 and audio[0]["codec_name"] == "aac" and len(pics) == 1
    assert data["format"]["tags"]["title"] == "Livre" and data["format"]["tags"]["artist"] == "Auteur"
    assert 4.5 <= float(data["format"]["duration"]) <= 5.5
