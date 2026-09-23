from __future__ import annotations

from bookmallow.names import safe_filename, unique_name

VID = "dQw4w9WgXcQ"


def test_basic_shape():
    assert safe_filename("Mon livre audio", VID) == f"Mon livre audio [{VID}].mp3"


def test_strips_forbidden_and_control_chars():
    name = safe_filename('A:B/C\\D*E?F"G<H>I|J\x07K', VID)
    assert name == f"ABCDEFGHIJK [{VID}].mp3"


def test_collapses_whitespace_and_trims_dots():
    assert safe_filename("  Titre   avec    espaces ... ", VID) == f"Titre avec espaces [{VID}].mp3"


def test_empty_title_falls_back():
    assert safe_filename("", VID) == f"audiobook [{VID}].mp3"
    assert safe_filename(None, VID) == f"audiobook [{VID}].mp3"
    assert safe_filename("???", VID) == f"audiobook [{VID}].mp3"


def test_truncates_to_max_len():
    name = safe_filename("x" * 500, VID, max_len=60)
    assert len(name) <= 60
    assert name.endswith(f" [{VID}].mp3")


def test_keeps_accents():
    assert safe_filename("Éloge de l'été — épisode 1", VID).startswith("Éloge de l'été — épisode 1")


def test_unique_name():
    existing = {"a.mp3", "a (2).mp3"}
    assert unique_name("b.mp3", existing) == "b.mp3"
    assert unique_name("a.mp3", existing) == "a (3).mp3"
    assert unique_name("noext", {"noext"}) == "noext (2)"
