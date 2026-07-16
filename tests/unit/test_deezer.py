from __future__ import annotations

import re

from pytest_httpx import HTTPXMock

from app.metadata.deezer import DeezerClient

_TRACK_DATA = {
    "id": 12345,
    "title": "Get Lucky",
    "title_short": "Get Lucky",
    "duration": 248,
    "bpm": 116.0,
    "gain": -12.5,
    "preview": "https://cdns-preview-d.dzcdn.net/stream/fake.mp3",
    "explicit_lyrics": False,
    "rank": 900000,
    "artist": {"name": "Daft Punk"},
    "album": {"title": "Random Access Memories"},
}


class TestDeezerSearch:
    async def test_search_returns_tracks(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"https://api[.]deezer[.]com/search.*"),
            json={"data": [_TRACK_DATA], "total": 1},
        )
        client = DeezerClient()
        results = await client.search_track("Get Lucky", "Daft Punk")
        assert len(results) == 1
        t = results[0]
        assert t.deezer_id == "12345"
        assert t.title == "Get Lucky"
        assert t.artist == "Daft Punk"
        assert t.bpm == 116.0
        assert t.gain == -12.5
        assert t.duration_sec == 248

    async def test_search_empty_results(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"https://api[.]deezer[.]com/search.*"),
            json={"data": [], "total": 0},
        )
        client = DeezerClient()
        results = await client.search_track("Nonexistent Track", "Nobody")
        assert results == []

    async def test_get_track_success(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.deezer.com/track/12345",
            json=_TRACK_DATA,
        )
        client = DeezerClient()
        track = await client.get_track("12345")
        assert track is not None
        assert track.deezer_id == "12345"
        assert track.preview_url is not None

    async def test_get_track_not_found(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://api.deezer.com/track/99999",
            status_code=404,
            json={"error": {"type": "DataException", "message": "no data"}},
        )
        client = DeezerClient()
        track = await client.get_track("99999")
        assert track is None
