from __future__ import annotations

import os

from bookmallow import retention


def make(tmp_path, name, age):
    """Create `name` whose mtime is `age` seconds in the past."""
    p = tmp_path / name
    p.write_bytes(b"x")
    t = 1_800_000_000 - age
    os.utime(p, (t, t))
    return p


def test_list_mp3_newest_first_ignoring_partials(tmp_path):
    make(tmp_path, "old.mp3", 300)
    make(tmp_path, "new.mp3", 10)
    make(tmp_path, "mid.mp3", 100)
    make(tmp_path, "wip.part.mp3", 0)
    make(tmp_path, "notes.txt", 0)
    assert [p.name for p in retention.list_mp3(tmp_path)] == ["new.mp3", "mid.mp3", "old.mp3"]


def test_prune_keeps_newest_n(tmp_path):
    for i in range(5):
        make(tmp_path, f"f{i}.mp3", i * 10)  # f0 newest, f4 oldest
    deleted = retention.prune(tmp_path, 3)
    assert sorted(p.name for p in deleted) == ["f3.mp3", "f4.mp3"]
    assert sorted(p.name for p in tmp_path.glob("*.mp3")) == ["f0.mp3", "f1.mp3", "f2.mp3"]


def test_prune_nothing_when_under_limit(tmp_path):
    make(tmp_path, "a.mp3", 0)
    assert retention.prune(tmp_path, 6) == []


def test_next_to_go(tmp_path):
    assert retention.next_to_go(tmp_path, 2) is None
    make(tmp_path, "a.mp3", 100)
    assert retention.next_to_go(tmp_path, 2) is None
    make(tmp_path, "b.mp3", 10)
    assert retention.next_to_go(tmp_path, 2) == "a.mp3"


def test_remove_partials(tmp_path):
    make(tmp_path, "keep.mp3", 0)
    make(tmp_path, "x.part.mp3", 0)
    make(tmp_path, "y.part.mp3", 0)
    removed = retention.remove_partials(tmp_path)
    assert sorted(p.name for p in removed) == ["x.part.mp3", "y.part.mp3"]
    assert [p.name for p in tmp_path.iterdir()] == ["keep.mp3"]
