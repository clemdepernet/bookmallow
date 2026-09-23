from __future__ import annotations

import pytest

from bookmallow import urls


@pytest.mark.parametrize("raw", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "http://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "youtube.com/watch?v=dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
])
def test_video_urls(raw):
    p = urls.parse(raw)
    assert p.video_id == "dQw4w9WgXcQ"
    assert p.is_playlist is False
    assert p.watch_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_playlist_only():
    p = urls.parse("https://www.youtube.com/playlist?list=PLabc123DEF")
    assert p.video_id is None
    assert p.playlist_id == "PLabc123DEF"
    assert p.is_playlist is True
    assert p.playlist_url == "https://www.youtube.com/playlist?list=PLabc123DEF"
    with pytest.raises(urls.InvalidUrl):
        _ = p.watch_url


def test_video_inside_playlist():
    p = urls.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc123DEF&index=3")
    assert p.video_id == "dQw4w9WgXcQ"
    assert p.playlist_id == "PLabc123DEF"
    assert p.is_playlist is True


@pytest.mark.parametrize("raw", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=ULdQw4w9WgXcQ",
])
def test_mix_and_radio_list_ids_are_ignored(raw):
    """A YouTube mix/radio `list=RD…`/`list=UL…` id is never a fetchable playlist (finding #1)."""
    p = urls.parse(raw)
    assert p.video_id == "dQw4w9WgXcQ"
    assert p.playlist_id is None
    assert p.is_playlist is False


@pytest.mark.parametrize("raw", [
    "", "   ", "https://vimeo.com/12345", "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/", "https://www.youtube.com/watch?v=short",
    "https://evil.com/?u=youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
    "javascript:alert(1)",
])
def test_rejects_non_youtube_or_idless(raw):
    with pytest.raises(urls.InvalidUrl):
        urls.parse(raw)


def test_watch_url_helper():
    assert urls.watch_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
