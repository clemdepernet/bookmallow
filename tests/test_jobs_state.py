from __future__ import annotations

import json

from bookmallow.jobs import ACTIVE_STATUSES, Job, Status, new_book_job, new_job, now_iso
from bookmallow.state import StateStore


def test_new_job_defaults():
    j = new_job("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ", "64")
    assert len(j.id) == 8
    assert j.status is Status.QUEUED
    assert j.is_active is True
    assert j.progress == 0.0
    assert j.created_at.endswith("+00:00")


def test_active_statuses():
    assert ACTIVE_STATUSES == {Status.QUEUED, Status.FETCHING, Status.CONVERTING}
    j = new_job("u", "v", "64")
    j.status = Status.DONE
    assert j.is_active is False


def test_roundtrip_dict():
    j = new_job("u", "v", "128")
    j.status = Status.FAILED
    j.error_code = "private"
    d = j.to_dict()
    assert d["status"] == "failed"
    assert Job.from_dict(d) == j


def test_from_dict_ignores_unknown_and_defaults_status():
    j = Job.from_dict({"id": "abcd1234", "url": "u", "video_id": "v", "quality": "64", "future_field": 1})
    assert j.status is Status.QUEUED


def test_now_iso_has_no_microseconds():
    assert "." not in now_iso()


def test_store_load_missing(tmp_path):
    assert StateStore(tmp_path / "state.json").load() == []


def test_store_save_and_load(tmp_path):
    store = StateStore(tmp_path / "state.json")
    jobs = [new_job("u1", "v1", "64"), new_job("u2", "v2", "192")]
    store.save(jobs)
    assert store.load() == jobs
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["version"] == 1
    assert not (tmp_path / "state.json.tmp").exists()


def test_store_corrupt_file_is_moved_aside(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert StateStore(path).load() == []
    assert not path.exists()
    assert (tmp_path / "state.json.bad").read_text() == "{not json"


def test_store_trims_finished_jobs_but_keeps_active(tmp_path):
    store = StateStore(tmp_path / "state.json", max_jobs=3)
    jobs = []
    for i in range(5):
        j = new_job(f"u{i}", f"v{i}", "64")
        j.created_at = f"2026-01-0{i + 1}T00:00:00+00:00"
        j.status = Status.DONE if i < 4 else Status.QUEUED
        jobs.append(j)
    kept = store.save(jobs)
    assert [j.video_id for j in kept] == ["v2", "v3", "v4"]
    assert [j.video_id for j in store.load()] == ["v2", "v3", "v4"]


def test_store_skips_unreadable_rows_but_keeps_the_rest(tmp_path):
    path = tmp_path / "state.json"
    good = new_job("u", "v", "64")
    rows = [good.to_dict(), {**good.to_dict(), "id": "bad00001", "status": "teleporting"}, "not-a-dict"]
    path.write_text(json.dumps({"version": 1, "jobs": rows}))
    assert StateStore(path).load() == [good]
    assert path.exists() and not (tmp_path / "state.json.bad").exists()


def test_job_defaults_keep_v1_shape():
    j = new_job("u", "v", "64")
    assert j.kind == "youtube" and j.source is None and j.author is None and j.torrent_hash is None and j.cover is None


def test_v1_state_dict_without_new_fields_still_loads():
    old = {"id": "abcd1234", "url": "u", "video_id": "v", "quality": "64", "status": "done", "title": "T"}
    j = Job.from_dict(old)
    assert j.kind == "youtube" and j.language is None


def test_new_book_job():
    j = new_book_job("librivox", "904", "Boule de suif", "Guy de Maupassant", "fr", 15251, "https://c/x.jpg", "64")
    assert j.kind == "book" and j.source == "librivox" and j.source_id == "904"
    assert j.video_id == "librivox:904" and j.url == "" and j.title == "Boule de suif"
    assert j.author == "Guy de Maupassant" and j.language == "fr" and j.duration == 15251
    assert j.cover == "https://c/x.jpg" and j.thumbnail == "https://c/x.jpg" and j.quality == "64"
    assert j.to_dict()["kind"] == "book"
