from __future__ import annotations

import re

from pytest_httpx import HTTPXMock

from app.schemas.search import SearchRequest
from app.sources.prowlarr import ProwlarrAdapter


class TestProwlarrHealth:
    async def test_health_ok_no_errors(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://prowlarr.local/api/v1/health",
            json=[],
        )
        adapter = ProwlarrAdapter("http://prowlarr.local", "key456")
        state = await adapter.health()
        assert state.available is True

    async def test_health_with_errors(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://prowlarr.local/api/v1/health",
            json=[{"type": "error", "message": "Indexer offline"}],
        )
        adapter = ProwlarrAdapter("http://prowlarr.local", "key456")
        state = await adapter.health()
        assert state.available is False
        assert "Indexer offline" in (state.reason or "")

    async def test_health_unconfigured(self) -> None:
        adapter = ProwlarrAdapter("", "")
        state = await adapter.health()
        assert state.available is False

    async def test_health_unreachable(self, httpx_mock: HTTPXMock) -> None:
        import httpx

        for _ in range(3):
            httpx_mock.add_exception(
                httpx.ConnectError("refused"),
                url="http://prowlarr.local/api/v1/health",
            )
        adapter = ProwlarrAdapter("http://prowlarr.local", "key456")
        state = await adapter.health()
        assert state.available is False


class TestProwlarrSearch:
    async def test_search_returns_results(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"http://prowlarr[.]local/api/v1/search.*"),
            json=[
                {
                    "title": "Artist - Album (2020) FLAC",
                    "size": 500000000,
                    "downloadUrl": "https://nzb.example.com/get/abc123.nzb",
                    "indexer": "NZBGeek",
                    "seeders": None,
                    "grabs": 5,
                    "publishDate": "2020-01-01T00:00:00Z",
                }
            ],
        )
        adapter = ProwlarrAdapter("http://prowlarr.local", "key456")
        req = SearchRequest(query="Artist Album 2020 FLAC")
        results = await adapter.search(req)
        assert len(results) == 1
        assert results[0].source == "prowlarr"
        assert results[0].format == "nzb"

    async def test_search_does_not_expose_magnet_as_nzb_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=re.compile(r"http://prowlarr[.]local/api/v1/search.*"),
            json=[
                {
                    "title": "Torrent Result",
                    "magnetUrl": "magnet:?xt=urn:btih:abc123",
                    "indexer": "TorrentIndexer",
                }
            ],
        )
        adapter = ProwlarrAdapter("http://prowlarr.local", "key456")
        req = SearchRequest(query="Artist Album 2020 FLAC")
        results = await adapter.search(req)

        assert len(results) == 1
        assert results[0].format is None
        assert results[0].url is None
