from __future__ import annotations

import io
import subprocess
import threading
import time
from pathlib import Path

import pytest

from bookmallow import converter as cv


def req(tmp_path, **kw) -> cv.ConvertRequest:
    base = dict(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", quality="64", out_path=tmp_path / "Livre [dQw4w9WgXcQ].mp3", duration=100)
    base.update(kw)
    return cv.ConvertRequest(**base)


class FakeProc:
    def __init__(self, cmd, stdout_bytes=b"", stderr_bytes=b"", rc=0):
        self.cmd = cmd
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self.rc = rc
        self.pid = 999999

    def wait(self):
        return self.rc

    def poll(self):
        return self.rc


def fake_popen(*, ff_progress=b"", ff_rc=0, ff_stderr=b"", yt_rc=0, yt_stderr=b"", write_part=True):
    """Return (popen, calls). First call = yt-dlp, second = ffmpeg."""
    calls = []

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0] == "yt-dlp":
            return FakeProc(cmd, stderr_bytes=yt_stderr, rc=yt_rc)
        if write_part:
            Path(cmd[-1]).write_bytes(b"ID3fake")
        return FakeProc(cmd, stdout_bytes=ff_progress, stderr_bytes=ff_stderr, rc=ff_rc)

    return popen, calls


def test_ytdlp_command_streams_to_stdout():
    cmd = cv.ytdlp_command("URL")
    assert cmd[0] == "yt-dlp" and cmd[-1] == "URL"
    assert cmd[cmd.index("-o") + 1] == "-"
    assert "--no-playlist" in cmd
    assert cmd[cmd.index("-f") + 1] == cv.YTDLP_FORMAT


def test_ffmpeg_command_quality_64_is_mono(tmp_path):
    cmd = cv.ffmpeg_command(req(tmp_path, title="Livre", channel="Chaîne"), None)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "pipe:0"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-b:a") + 1] == "64k"
    assert cmd[cmd.index("-codec:a") + 1] == "libmp3lame"
    assert "-progress" in cmd and cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert cmd[-1] == str(tmp_path / "Livre [dQw4w9WgXcQ].part.mp3")
    assert "title=Livre" in cmd and "artist=Chaîne" in cmd


def test_ffmpeg_command_quality_192_is_stereo_and_uses_meta_file(tmp_path):
    cmd = cv.ffmpeg_command(req(tmp_path, quality="192"), tmp_path / "m.ffmeta")
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-b:a") + 1] == "192k"
    assert str(tmp_path / "m.ffmeta") in cmd
    assert "-map_chapters" in cmd and "-map_metadata" in cmd


def test_write_ffmetadata_escapes_and_lists_chapters(tmp_path):
    r = req(tmp_path, title="A=B;C", channel="X", chapters=[{"title": "Un", "start": 0, "end": 1.5}, {"title": "Vide", "start": 5, "end": 5}])
    text = cv.write_ffmetadata(r)
    assert text.startswith(";FFMETADATA1\n")
    assert "title=A\\=B\\;C" in text
    assert text.count("[CHAPTER]") == 1
    assert "START=0\nEND=1500\ntitle=Un" in text


@pytest.mark.parametrize("line,expected", [
    ("out_time_us=1500000", 1_500_000), ("out_time_ms=1500000", 1_500_000), ("out_time_us=-1", 0),
    ("frame=12", None), ("out_time=00:00:01.5", None), ("out_time_us=abc", None), ("", None),
])
def test_parse_progress_line(line, expected):
    assert cv.parse_progress_line(line) == expected


def test_progress_percent():
    assert cv.progress_percent(50_000_000, 100) == 50.0
    assert cv.progress_percent(500_000_000, 100) == 99.9
    assert cv.progress_percent(10, None) == 0.0


def test_run_success_renames_part_and_reports_progress(tmp_path):
    popen, calls = fake_popen(ff_progress=b"frame=1\nout_time_us=25000000\nprogress=continue\nout_time_us=100000000\nprogress=end\n")
    seen = []
    r = req(tmp_path)
    cv.Conversion(r, on_progress=seen.append, popen=popen).run()
    assert r.out_path.exists() and not r.part_path.exists()
    assert seen == [25.0, 99.9]
    (yt_cmd, yt_kw), (ff_cmd, ff_kw) = calls
    assert yt_cmd[0] == "yt-dlp" and ff_cmd[0] == "ffmpeg"
    assert yt_kw["stdout"] is subprocess.PIPE and yt_kw["start_new_session"] is True
    assert ff_kw["start_new_session"] is True


def test_run_writes_metadata_file_when_chapters_and_cleans_it(tmp_path):
    popen, calls = fake_popen()
    r = req(tmp_path, chapters=[{"title": "Un", "start": 0, "end": 10}])
    cv.Conversion(r, popen=popen).run()
    ff_cmd = calls[1][0]
    assert any(arg.endswith(".ffmeta") for arg in ff_cmd)
    assert not list(tmp_path.glob("*.ffmeta"))


def test_run_ffmpeg_failure(tmp_path):
    popen, _ = fake_popen(ff_rc=1, ff_stderr=b"pipe:0: Invalid data found when processing input\n")
    r = req(tmp_path)
    with pytest.raises(cv.ConversionError) as exc:
        cv.Conversion(r, popen=popen).run()
    assert exc.value.code == "ffmpeg"
    assert "Invalid data" in exc.value.detail
    assert not r.part_path.exists() and not r.out_path.exists()


def test_run_ytdlp_error_wins_over_ffmpeg_noise(tmp_path):
    popen, _ = fake_popen(ff_rc=1, ff_stderr=b"pipe:0: Invalid data\n", yt_rc=1,
                          yt_stderr=b"ERROR: [youtube] dQw4w9WgXcQ: Private video\n")
    with pytest.raises(cv.ConversionError) as exc:
        cv.Conversion(req(tmp_path), popen=popen).run()
    assert exc.value.code == "private"


def test_run_broken_pipe_from_ytdlp_is_reported_as_ffmpeg(tmp_path):
    popen, _ = fake_popen(ff_rc=1, ff_stderr=b"Conversion failed!\n", yt_rc=1,
                          yt_stderr=b"ERROR: unable to write data: [Errno 32] Broken pipe\n")
    with pytest.raises(cv.ConversionError) as exc:
        cv.Conversion(req(tmp_path), popen=popen).run()
    assert exc.value.code == "ffmpeg"


def test_cancel_before_run_raises_cancelled(tmp_path):
    popen, _ = fake_popen()
    r = req(tmp_path)
    conv = cv.Conversion(r, popen=popen, kill_grace=0.01)
    conv.cancel()
    with pytest.raises(cv.Cancelled):
        conv.run()
    assert not r.part_path.exists()


def test_cancel_kills_real_processes(tmp_path):
    """Both fake tools are `sleep 30`; cancel() must end run() quickly via SIGTERM on the process groups."""
    def popen(cmd, **kw):
        return subprocess.Popen(["sleep", "30"], **kw)

    conv = cv.Conversion(req(tmp_path), popen=popen, kill_grace=1.0)
    result = {}

    def target():
        try:
            conv.run()
        except BaseException as exc:  # noqa: BLE001
            result["exc"] = exc

    t = threading.Thread(target=target)
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    conv.cancel()
    t.join(timeout=5)
    assert not t.is_alive()
    assert isinstance(result["exc"], cv.Cancelled)
    assert time.monotonic() - started < 4
