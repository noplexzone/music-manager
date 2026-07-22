from __future__ import annotations

import pytest

from app.display_names import display_name


@pytest.mark.parametrize(
    "key,expected",
    [
        ("slskd", "Soulseek (slskd)"),
        ("prowlarr", "Prowlarr"),
        ("sabnzbd", "SABnzbd"),
        ("youtube", "YouTube (yt-dlp)"),
        ("tidal", "TIDAL"),
        ("musicbrainz", "MusicBrainz"),
        ("deezer", "Deezer"),
        ("itunes", "iTunes / Apple Music"),
    ],
)
def test_known_keys(key: str, expected: str) -> None:
    assert display_name(key) == expected


def test_unknown_key_returns_key() -> None:
    assert display_name("unknown_source") == "unknown_source"


def test_empty_key_returns_empty() -> None:
    assert display_name("") == ""
