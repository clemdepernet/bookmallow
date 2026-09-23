from __future__ import annotations

from dataclasses import replace

import pytest

from bookmallow.app import build_state, create_app, resolve_file
from bookmallow.jobqueue import JobQueue
from bookmallow.jobs import Status, new_job
from bookmallow.metadata import MetadataError, PlaylistEntry, PlaylistMeta
from bookmallow.state import StateStore

WATCH = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def fake_playlist(url, **kwargs):
    return PlaylistMeta("PL1", "Ma liste", [PlaylistEntry(c * 11, f"Partie {c}", 10) for c in "abcdefgh"])


def make_client(config, fetch_playlist=fake_playlist):
    q = JobQueue(config, StateStore(config.state_path), fetch_video=lambda u: None, conversion_factory=None)
    q.recover()
    app = create_app(config, jobqueue=q, start_worker=False, fetch_playlist=fetch_playlist)
    app.config["TESTING"] = True
    client = app.test_client()
    client.queue = q
    return client


@pytest.fixture
def client(config):
    return make_client(config)


@pytest.fixture
def auth_client(config):
    return make_client(replace(config, app_password="pink"))


def test_healthz(client):
    assert client.get("/healthz").get_json() == {"ok": True}


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Bookmallow" in r.data


def test_security_headers_present(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "img-src 'self' data: https://i.ytimg.com https://*.ggpht.com" in csp
    assert "frame-ancestors 'none'" in csp


def test_state_shape(client, config):
    (config.data_dir / "Old [aaaaaaaaaaa].mp3").write_bytes(b"x" * 10)
    d = client.get("/api/state").get_json()
    assert d["jobs"] == []
    f = d["files"][0]
    assert f["name"] == "Old [aaaaaaaaaaa].mp3" and f["size_bytes"] == 10 and f["title"] == "Old [aaaaaaaaaaa]"
    assert f["thumbnail"] is None and f["job_id"] is None and f["modified_at"].endswith("+00:00")
    assert d["retention"] == {"max_files": 6, "count": 1, "next_to_go": None}
    assert d["config"] == {"max_files": 6, "qualities": ["64", "128", "192"], "default_quality": "64",
                           "default_lang": "fr", "auth_enabled": False}


def test_state_joins_done_jobs_and_flags_expired(client, config):
    q = client.queue
    done = new_job(WATCH, "dQw4w9WgXcQ", "128")
    done.status, done.title, done.thumbnail, done.filename = Status.DONE, "Livre", "https://i/x.jpg", "Livre [dQw4w9WgXcQ].mp3"
    gone = new_job(WATCH, "bbbbbbbbbbb", "64")
    gone.status, gone.filename = Status.DONE, "Gone [bbbbbbbbbbb].mp3"
    q.jobs.extend([done, gone])
    (config.data_dir / done.filename).write_bytes(b"x")
    d = client.get("/api/state").get_json()
    assert d["files"][0]["title"] == "Livre" and d["files"][0]["thumbnail"] == "https://i/x.jpg"
    assert d["files"][0]["quality"] == "128" and d["files"][0]["job_id"] == done.id
    by_id = {j["id"]: j for j in d["jobs"]}
    assert by_id[done.id]["expired"] is False and by_id[gone.id]["expired"] is True


def test_submit_video(client):
    r = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ", "quality": "128"})
    assert r.status_code == 201
    job = r.get_json()["jobs"][0]
    assert job["video_id"] == "dQw4w9WgXcQ" and job["quality"] == "128" and job["status"] == "queued"
    assert job["url"] == WATCH
    assert client.queue.get(job["id"]) is not None


def test_submit_uses_default_quality(client):
    job = client.post("/api/jobs", json={"url": WATCH}).get_json()["jobs"][0]
    assert job["quality"] == "64"


def test_submit_rejects_bad_quality_and_url(client):
    assert client.post("/api/jobs", json={"url": WATCH, "quality": "320"}).status_code == 400
    r = client.post("/api/jobs", json={"url": "https://vimeo.com/1"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_url"
    assert client.post("/api/jobs", data="not json", content_type="text/plain").status_code == 400


def test_submit_duplicate(client):
    client.post("/api/jobs", json={"url": WATCH})
    r = client.post("/api/jobs", json={"url": WATCH})
    assert r.status_code == 409 and r.get_json()["error"] == "duplicate" and len(r.get_json()["jobs"]) == 1


def test_playlist_preview(client):
    r = client.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 200
    pl = r.get_json()["playlist"]
    assert pl["title"] == "Ma liste" and pl["count"] == 8 and pl["max_files"] == 6
    assert pl["single_video_url"] is None
    assert pl["entries"][0] == {"video_id": "aaaaaaaaaaa", "title": "Partie a", "duration": 10}


def test_playlist_preview_with_video_offers_single(client):
    r = client.post("/api/jobs", json={"url": WATCH + "&list=PL1"})
    assert r.get_json()["playlist"]["single_video_url"] == WATCH


def test_playlist_ignore_queues_single_video(client):
    r = client.post("/api/jobs", json={"url": WATCH + "&list=PL1", "playlist": "ignore"})
    assert r.status_code == 201 and r.get_json()["jobs"][0]["video_id"] == "dQw4w9WgXcQ"


def test_playlist_expand_is_capped_to_max_files(client):
    r = client.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1", "playlist": "expand"})
    assert r.status_code == 201
    assert [j["video_id"] for j in r.get_json()["jobs"]] == [c * 11 for c in "abcdef"]


def test_playlist_expand_selected_ids(client):
    r = client.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1", "playlist": "expand",
                                       "video_ids": ["ccccccccccc", "hhhhhhhhhhh", "zzzzzzzzzzz"]})
    assert [j["video_id"] for j in r.get_json()["jobs"]] == ["ccccccccccc", "hhhhhhhhhhh"]


def test_playlist_error(config):
    def boom(url, **kwargs):
        raise MetadataError("unavailable", "gone")
    c = make_client(config, fetch_playlist=boom)
    r = c.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 502 and r.get_json() == {"error": "metadata", "code": "unavailable", "detail": "gone"}


def test_mix_list_id_is_not_a_playlist(config):
    """A `list=RD…` mix/radio id must not trigger a playlist lookup at all (finding #1)."""
    calls = []

    def tracking_fetch(url, **kwargs):
        calls.append(url)
        raise AssertionError("fetch_playlist must not be called for a mix/radio list id")

    c = make_client(config, fetch_playlist=tracking_fetch)
    r = c.post("/api/jobs", json={"url": WATCH + "&list=RDdQw4w9WgXcQ&start_radio=1"})
    assert r.status_code == 201
    assert r.get_json()["jobs"][0]["video_id"] == "dQw4w9WgXcQ"
    assert "playlist_error" not in r.get_json()
    assert calls == []


def test_playlist_error_falls_back_to_single_video_when_video_id_present(config):
    def boom(url, **kwargs):
        raise MetadataError("unavailable", "This playlist type is unviewable")
    c = make_client(config, fetch_playlist=boom)
    r = c.post("/api/jobs", json={"url": WATCH + "&list=PL1"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["jobs"][0]["video_id"] == "dQw4w9WgXcQ"
    assert body["playlist_error"] == "unavailable"


def test_playlist_only_error_stays_502(config):
    """No video id in the URL: there is no single-video fallback, so the 502 stands."""
    def boom(url, **kwargs):
        raise MetadataError("unavailable", "gone")
    c = make_client(config, fetch_playlist=boom)
    r = c.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 502


def test_cancel_job(client):
    job = client.post("/api/jobs", json={"url": WATCH}).get_json()["jobs"][0]
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert client.queue.get(job["id"]).status is Status.CANCELLED
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 404


def test_download_file(client, config):
    (config.data_dir / "Livre [dQw4w9WgXcQ].mp3").write_bytes(b"0123456789")
    r = client.get("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3")
    assert r.status_code == 200 and r.data == b"0123456789"
    assert "attachment" in r.headers["Content-Disposition"]
    r.close()
    r = client.get("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.data == b"0123"
    r.close()


def test_download_refuses_missing_traversal_and_non_mp3(client, config):
    (config.data_dir.parent / "secret.mp3").write_bytes(b"s")
    (config.data_dir / "wip.part.mp3").write_bytes(b"w")
    assert client.get("/api/files/..%2Fsecret.mp3").status_code == 404
    assert client.get("/api/files/nope.mp3").status_code == 404
    assert client.get("/api/files/state.json").status_code == 404
    assert client.get("/api/files/wip.part.mp3").status_code == 404


def test_resolve_file(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"a")
    assert resolve_file(tmp_path, "a.mp3") == "a.mp3"
    assert resolve_file(tmp_path, "b.mp3") is None
    assert resolve_file(tmp_path, "../a.mp3") is None
    assert resolve_file(tmp_path, "a.mp3/") is None


def test_delete_file(client, config):
    p = config.data_dir / "Livre [dQw4w9WgXcQ].mp3"
    p.write_bytes(b"x")
    assert client.delete("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3").status_code == 204
    assert not p.exists()
    assert client.delete("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3").status_code == 404


def test_login_page_redirects_when_auth_disabled(client):
    r = client.get("/login")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


def test_auth_pages_redirect_and_api_401(auth_client):
    r = auth_client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = auth_client.get("/api/state")
    assert r.status_code == 401 and r.get_json() == {"error": "unauthorized"}
    assert auth_client.post("/api/jobs", json={"url": WATCH}).status_code == 401


def test_auth_login_flow(auth_client):
    assert auth_client.post("/login", data={"password": "nope"}).status_code == 401
    r = auth_client.post("/login?next=/", data={"password": "pink"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert auth_client.get("/").status_code == 200
    assert auth_client.get("/api/state").status_code == 200
    r = auth_client.post("/logout")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert auth_client.get("/api/state").status_code == 401


def test_unauthenticated_get_download_redirects_to_login(auth_client):
    """A GET on a download link from an expired session should send a browser to /login, not raw JSON (finding #11)."""
    r = auth_client.get("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3")
    assert r.status_code == 302
    location = r.headers["Location"]
    assert location.startswith("/login?next=")
    assert "/api/files/Livre" in location
    # Every other unauthenticated /api/ call keeps returning JSON.
    assert auth_client.delete("/api/files/Livre%20%5BdQw4w9WgXcQ%5D.mp3").status_code == 401
    assert auth_client.get("/api/state").status_code == 401


def test_auth_open_redirect_blocked(auth_client):
    r = auth_client.post("/login?next=//evil.com/x", data={"password": "pink"})
    assert r.headers["Location"] in ("/", "http://localhost/")
    r = auth_client.post("/login?next=https://evil.com", data={"password": "pink"})
    assert r.headers["Location"] in ("/", "http://localhost/")


def test_build_state_direct(config, client):
    d = build_state(config, client.queue)
    assert set(d) == {"jobs", "files", "retention", "config"}


def test_build_state_survives_file_vanishing_between_list_and_stat(client, config, monkeypatch):
    """/api/state must not 500 when retention/another request deletes a listed file mid-request (finding #3)."""
    (config.data_dir / "keep.mp3").write_bytes(b"x" * 5)
    (config.data_dir / "ghost.mp3").write_bytes(b"y" * 5)
    from pathlib import Path as PathCls
    real_stat = PathCls.stat

    def flaky_stat(self, *a, **kw):
        if self.name == "ghost.mp3":
            raise FileNotFoundError(self)
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(PathCls, "stat", flaky_stat)
    r = client.get("/api/state")
    assert r.status_code == 200
    names = {f["name"] for f in r.get_json()["files"]}
    assert names == {"keep.mp3"}


def test_playlist_preview_passes_limit_to_yt_dlp(config):
    calls = []

    def spy(url, runner=None, timeout=90.0, limit=200):
        calls.append(limit)
        return PlaylistMeta("PL1", "Ma liste", [])

    c = make_client(config, fetch_playlist=spy)
    c.post("/api/jobs", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert calls == [200]
