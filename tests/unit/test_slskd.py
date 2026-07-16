from __future__ import annotations

from pytest_httpx import HTTPXMock

from app.schemas.search import SearchRequest
from app.sources.slskd import SlskdAdapter


class TestSlskdHealth:
    async def test_health_ok(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://slskd.local/api/v0/application",
            json={"version": "0.21.0", "state": "Connected"},
        )
        adapter = SlskdAdapter("http://slskd.local", "key123")
        state = await adapter.health()
        assert state.available is True

    async def test_health_unreachable(self, httpx_mock: HTTPXMock) -> None:
        import httpx as httpx_lib

        for _ in range(3):
            httpx_mock.add_exception(
                httpx_lib.ConnectError("Connection refused"),
                url="http://slskd.local/api/v0/application",
            )
        adapter = SlskdAdapter("http://slskd.local", "key123")
        state = await adapter.health()
        assert state.available is False
        assert state.reason is not None

    async def test_health_unconfigured(self) -> None:
        adapter = SlskdAdapter("", "")
        state = await adapter.health()
        assert state.available is False
        assert "not configured" in (state.reason or "")


class TestSlskdSearch:
    async def test_search_returns_results(self, httpx_mock: HTTPXMock) -> None:
        search_id = "abc123"
        httpx_mock.add_response(
            url="http://slskd.local/api/v0/searches",
            method="POST",
            json={"id": search_id},
        )
        httpx_mock.add_response(
            url=f"http://slskd.local/api/v0/searches/{search_id}",
            json={"state": "Completed", "id": search_id},
        )
        httpx_mock.add_response(
            url=f"http://slskd.local/api/v0/searches/{search_id}/responses",
            json=[
                {
                    "username": "peer1",
                    "files": [
                        {
                            "filename": "music/Artist/Album/01 Song.flac",
                            "size": 30000000,
                            "bitRate": 1411,
                            "sampleRate": 44100,
                        }
                    ],
                }
            ],
        )
        adapter = SlskdAdapter("http://slskd.local", "key123")
        req = SearchRequest(query="Artist Album Song")
        results = await adapter.search(req)
        assert len(results) == 1
        assert results[0].source == "slskd"
        assert results[0].format == "flac"
        assert results[0].size_bytes == 30000000
