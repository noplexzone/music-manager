from __future__ import annotations

import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.metadata.musicbrainz import MusicBrainzClient

UA = "test-app/0.1.0 (test@example.com)"


class TestLookupRecording:
    async def test_successful_lookup(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"https://musicbrainz.org/ws/2/recording/test-mbid-1234.*"),
            json={
                "id": "test-mbid-1234",
                "title": "Bohemian Rhapsody",
                "length": 354000,
                "artist-credit": [{"artist": {"name": "Queen"}, "joinphrase": ""}],
                "releases": [
                    {
                        "title": "A Night at the Opera",
                        "date": "1975-11-21",
                        "media-count": 1,
                        "media": [
                            {
                                "position": 1,
                                "track": [{"number": "11"}],
                            }
                        ],
                    }
                ],
            },
        )
        client = MusicBrainzClient(UA)
        result = await client.lookup_recording("test-mbid-1234")
        assert result is not None
        assert result.mbid == "test-mbid-1234"
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.album == "A Night at the Opera"
        assert result.year == "1975"
        assert result.duration_ms == 354000

    async def test_not_found_returns_none(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"https://musicbrainz[.]org/ws/2/recording/nonexistent.*"),
            status_code=404,
            json={"error": "Not Found"},
        )
        client = MusicBrainzClient(UA)
        result = await client.lookup_recording("nonexistent")
        assert result is None

    async def test_search_returns_list(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"https://musicbrainz[.]org/ws/2/recording[?].*"),
            json={
                "recordings": [
                    {
                        "id": "rec-001",
                        "title": "Yesterday",
                        "length": 125000,
                        "artist-credit": [{"artist": {"name": "The Beatles"}, "joinphrase": ""}],
                        "releases": [],
                    }
                ]
            },
        )
        client = MusicBrainzClient(UA)
        results = await client.search_recording("Yesterday", artist="The Beatles")
        assert len(results) == 1
        assert results[0].mbid == "rec-001"
        assert results[0].title == "Yesterday"


class TestMusicBrainzRetry:
    async def test_503_retries_then_succeeds(self, httpx_mock: HTTPXMock) -> None:
        url = re.compile(r"https://musicbrainz[.]org/ws/2/recording/flaky.*")
        httpx_mock.add_response(url=url, status_code=503, json={"error": "try later"})
        httpx_mock.add_response(
            url=url,
            json={"id": "flaky", "title": "Recovered", "artist-credit": [], "releases": []},
        )

        client = MusicBrainzClient(UA)
        result = await client.lookup_recording("flaky")

        assert result is not None
        assert result.mbid == "flaky"

    async def test_503_raises_after_three_failures(self, httpx_mock: HTTPXMock) -> None:
        url = re.compile(r"https://musicbrainz[.]org/ws/2/recording/down.*")
        for _ in range(3):
            httpx_mock.add_response(url=url, status_code=503, json={"error": "down"})

        client = MusicBrainzClient(UA)
        with pytest.raises(httpx.HTTPStatusError):
            await client.lookup_recording("down")
