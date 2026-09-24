from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from bookmallow import procutil
from bookmallow.converter import Cancelled, ConversionError
from bookmallow.store import assemble as asm
from bookmallow.store.models import StoreError, Track

TRACKS = [Track("https://archive.org/download/x/a%201.mp3", 10.0, "Un"), Track("https://archive.org/download/x/b's.mp3", 5.5, "Deux")]


def req(tmp_path, **kw):
    base = dict(tracks=list(TRACKS), out_path=tmp_path / "Livre [Auteur].m4b", work_dir=tmp_path / ".work" / "job1",
                title="Livre", author="Auteur", language="fr", duration=15, cover="https://c/cover.jpg", bitrate="64k")
    base.update(kw)
    return asm.AssembleRequest(**base)


class FakeProc:
    def __init__(self, cmd, stdout=b"", rc=0):
        self.cmd, self.stdout, self.stderr, self.rc, self.pid = cmd, io.BytesIO(stdout), io.BytesIO(b"err line\n"), rc, 4242

    def wait(self):
        return self.rc

    def poll(self):
        return self.rc


def fake_popen(progress=b"out_time_us=7500000\nprogress=end\n", rc=0, write=True):
    """`rc` may be a list: one exit code per successive ffmpeg run."""
    calls = []
    codes = list(rc) if isinstance(rc, (list, tuple)) else None

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        if write:
            Path(cmd[-1]).write_bytes(b"m4b")
        code = codes.pop(0) if codes is not None else rc
        return FakeProc(cmd, progress if "-progress" in cmd else b"", code)

    popen.calls = calls
    return popen


def ok_cover(url, timeout=10.0, max_bytes=5_000_000):
    return b"\xff\xd8jpeg", "image/jpeg"


def test_procutil_helpers(tmp_path):
    assert procutil.escape_ffmetadata("a=b;c#d\\e\nf") == "a\\=b\\;c\\#d\\\\e\\\nf"
    assert procutil.parse_progress_line("out_time_us=1500000") == 1_500_000 and procutil.parse_progress_line("x") is None
    assert procutil.progress_percent(50_000_000, 100) == 50.0
    p = tmp_path / "gone"
    procutil.unlink_quietly(p)  # no error when missing
    s = io.BytesIO(b"x")
    procutil.close_quietly(s, None)
    assert s.closed


def test_concat_list_escapes_quotes():
    text = asm.concat_list(TRACKS)
    assert text.splitlines()[0] == "ffconcat version 1.0"
    assert "file 'https://archive.org/download/x/a%201.mp3'" in text
    assert "file 'https://archive.org/download/x/b'\\''s.mp3'" in text


def test_concat_list_adds_http_options_to_remote_tracks_only():
    lines = asm.concat_list([Track("https://a/1.mp3", 1.0), Track("/incoming/Book/02.mp3", 1.0), Track("HTTP://b/3.mp3")]).splitlines()
    options = ["option rw_timeout 30000000", "option reconnect 1", "option reconnect_on_network_error 1",
               "option reconnect_on_http_error 429,5xx", "option reconnect_delay_max 60"]
    assert lines == ["ffconcat version 1.0", "file 'https://a/1.mp3'", *options, "file '/incoming/Book/02.mp3'",
                     "file 'HTTP://b/3.mp3'", *options]


def test_chapters_from_tracks():
    assert asm.chapters_from_tracks(TRACKS) == [{"title": "Un", "start": 0.0, "end": 10.0}, {"title": "Deux", "start": 10.0, "end": 15.5}]
    assert asm.chapters_from_tracks([Track("u", None, "x")]) == []
    assert asm.chapters_from_tracks([Track("u", 3.0, "")]) == [{"title": "Chapter 1", "start": 0.0, "end": 3.0}]


def test_ffmetadata_has_tags_and_chapters(tmp_path):
    text = asm.ffmetadata(req(tmp_path, title="A=B", source_url="https://librivox.org/x"))
    assert text.startswith(";FFMETADATA1\n") and "title=A\\=B" in text and "artist=Auteur" in text
    assert "album=A\\=B" in text and "genre=Audiobook" in text and "comment=https://librivox.org/x" in text
    assert text.count("[CHAPTER]") == 2 and "START=10000\nEND=15500\ntitle=Deux" in text


def test_ffmpeg_command_reencode_has_no_cover_stream(tmp_path):
    r = req(tmp_path)
    cmd = asm.ffmpeg_command(r, tmp_path / "list.txt", tmp_path / "meta.ffm")
    assert cmd[0] == "ffmpeg" and cmd[cmd.index("-protocol_whitelist") + 1] == "file,http,https,tcp,tls,crypto"
    assert cmd[cmd.index("-f") + 1] == "concat" and "-safe" in cmd
    assert cmd.count("-i") == 2 and "-map_chapters" in cmd and "2:v" not in cmd and "attached_pic" not in cmd
    assert cmd[cmd.index("-map") + 1] == "0:a"
    assert cmd[cmd.index("-c:a") + 1] == "aac" and cmd[cmd.index("-b:a") + 1] == "64k" and cmd[cmd.index("-ac") + 1] == "1"
    assert "+faststart" in cmd and cmd[-2:] == ["ipod", str(tmp_path / "Livre [Auteur].part.m4b")]
    assert cmd[cmd.index("-progress") + 1] == "pipe:1"


def test_ffmpeg_command_copy(tmp_path):
    cmd = asm.ffmpeg_command(req(tmp_path, copy_audio=True, cover=None), tmp_path / "l", tmp_path / "m")
    assert cmd.count("-i") == 2 and cmd[cmd.index("-c:a") + 1] == "copy" and "-b:a" not in cmd and "attached_pic" not in cmd


def test_remux_cover_command(tmp_path):
    part, cover, out = tmp_path / "a.part.m4b", tmp_path / "cover.jpg", tmp_path / "a.part.cover.m4b"
    cmd = asm.remux_cover_command(part, cover, out)
    assert cmd[:5] == ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    assert cmd[cmd.index("-i") + 1] == str(part) and cmd.count("-i") == 2 and str(cover) in cmd
    maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
    assert maps == ["0:a", "1:v"] and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-disposition:v") + 1] == "attached_pic" and "+faststart" in cmd and "-progress" not in cmd
    assert cmd[-3:] == ["-f", "ipod", str(out)]


def test_cover_part_path_is_partial(tmp_path):
    r = req(tmp_path)
    assert r.cover_part_path.name == "Livre [Auteur].part.cover.m4b" and ".part." in r.cover_part_path.name


def test_cover_filename():
    assert asm.cover_filename("image/jpeg") == "cover.jpg" and asm.cover_filename("image/png") == "cover.png"
    assert asm.cover_filename("text/html") is None


def test_run_with_cover_encodes_then_remuxes(tmp_path):
    popen = fake_popen()
    r = req(tmp_path)
    seen = []
    asm.Assembly(r, on_progress=seen.append, popen=popen, fetch_bytes=ok_cover).run()
    assert r.out_path.exists() and not r.part_path.exists() and not r.cover_part_path.exists()
    assert seen == [50.0]  # progress comes from the audio pass only
    assert len(popen.calls) == 2
    (enc, kw), (remux, kw2) = popen.calls
    assert kw["start_new_session"] is True and kw["stdout"] is subprocess.PIPE and kw2["start_new_session"] is True
    assert any(str(a).endswith("list.txt") for a in enc) and not any(str(a).endswith("cover.jpg") for a in enc)
    assert enc[-1] == str(r.part_path)
    assert remux[remux.index("-i") + 1] == str(r.part_path) and any(str(a).endswith("cover.jpg") for a in remux)
    assert remux[-1] == str(r.cover_part_path)
    assert not r.work_dir.exists()


def test_run_without_cover_is_one_pass(tmp_path):
    popen = fake_popen()
    r = req(tmp_path, cover=None)
    asm.Assembly(r, popen=popen, fetch_bytes=ok_cover).run()
    assert len(popen.calls) == 1 and r.out_path.exists() and not r.part_path.exists()


def test_run_without_cover_when_download_fails(tmp_path):
    def bad_cover(url, timeout=10.0, max_bytes=5_000_000):
        raise StoreError("provider_error", "nope")
    popen = fake_popen()
    asm.Assembly(req(tmp_path), popen=popen, fetch_bytes=bad_cover).run()
    assert len(popen.calls) == 1 and "attached_pic" not in popen.calls[0][0]


def test_run_uses_local_cover_path(tmp_path):
    local = tmp_path / "folder.jpg"
    local.write_bytes(b"jpg")
    popen = fake_popen()
    asm.Assembly(req(tmp_path, cover=str(local)), popen=popen, fetch_bytes=None).run()
    assert len(popen.calls) == 2 and str(local) in popen.calls[1][0] and str(local) not in popen.calls[0][0]


def test_run_remux_failure_removes_both_partials(tmp_path):
    r = req(tmp_path)
    with pytest.raises(ConversionError) as exc:
        asm.Assembly(r, popen=fake_popen(rc=[0, 1]), fetch_bytes=ok_cover).run()
    assert exc.value.code == "ffmpeg" and exc.value.detail == "err line"
    assert not r.part_path.exists() and not r.cover_part_path.exists() and not r.out_path.exists()
    assert not r.work_dir.exists()


def test_cancel_between_passes_skips_remux(tmp_path):
    popen = fake_popen()
    r = req(tmp_path)
    holder = {}

    def on_progress(p):
        holder["a"].cancel()

    holder["a"] = asm.Assembly(r, on_progress=on_progress, popen=popen, fetch_bytes=ok_cover, kill_grace=0.01)
    with pytest.raises(Cancelled):
        holder["a"].run()
    assert len(popen.calls) == 1 and not r.part_path.exists() and not r.out_path.exists()


def test_run_failure_removes_part_and_keeps_tail(tmp_path):
    r = req(tmp_path)
    with pytest.raises(ConversionError) as exc:
        asm.Assembly(r, popen=fake_popen(rc=1), fetch_bytes=ok_cover).run()
    assert exc.value.code == "ffmpeg" and exc.value.detail == "err line" and "err line" in exc.value.tail
    assert not r.part_path.exists() and not r.out_path.exists() and not r.work_dir.exists()


def test_cancel_before_run(tmp_path):
    a = asm.Assembly(req(tmp_path), popen=fake_popen(), fetch_bytes=ok_cover, kill_grace=0.01)
    a.cancel()
    with pytest.raises(Cancelled):
        a.run()
