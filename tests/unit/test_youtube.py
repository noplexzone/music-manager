from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.schemas.search import SearchRequest
from app.sources.youtube import YouTubeAdapter


class TestYouTubeHealth:
    async def test_health_available_when_ytdlp_installed(self) -> None:
        with patch("app.sources.youtube._ytdlp_available", return_value=True):
            adapter = YouTubeAdapter()
            state = await adapter.health()
        assert state.available is True

    async def test_health_unavailable_when_ytdlp_missing(self) -> None:
        with patch("app.sources.youtube._ytdlp_available", return_value=False):
            adapter = YouTubeAdapter()
            state = await adapter.health()
        assert state.available is False
        assert "yt-dlp" in (state.reason or "")


class TestYouTubeSearch:
    async def test_search_returns_results(self) -> None:
        mock_info = {
            "entries": [
                {
                    "id": "dQw4w9WgXcQ",
                    "title": "Rick Astley - Never Gonna Give You Up",
                    "channel": "RickAstleyVEVO",
                    "duration": 213,
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "view_count": 1400000000,
                    "upload_date": "20091025",
                }
            ]
        }
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=mock_info)

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("yt_dlp.YoutubeDL", return_value=mock_ydl),
        ):
            adapter = YouTubeAdapter()
            results = await adapter.search(SearchRequest(query="Never Gonna Give You Up"))

        assert len(results) == 1
        assert results[0].source == "youtube"
        assert results[0].duration_sec == 213
        assert results[0].title is not None

    async def test_search_empty_when_ytdlp_missing(self) -> None:
        with patch("app.sources.youtube._ytdlp_available", return_value=False):
            adapter = YouTubeAdapter()
            results = await adapter.search(SearchRequest(query="test"))
        assert results == []

    async def test_search_returns_empty_on_exception(self) -> None:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(side_effect=Exception("network error"))

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("yt_dlp.YoutubeDL", return_value=mock_ydl),
        ):
            adapter = YouTubeAdapter()
            results = await adapter.search(SearchRequest(query="test"))

        assert results == []

    async def test_search_runs_ytdlp_in_worker_thread(self) -> None:
        mock_info: dict[str, object] = {"entries": []}
        calls: list[str] = []

        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
            calls.append(getattr(func, "__name__", repr(func)))
            return mock_info

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.to_thread", side_effect=fake_to_thread),
        ):
            adapter = YouTubeAdapter(search_timeout_sec=5.0)
            results = await adapter.search(SearchRequest(query="test"))

        assert results == []
        assert calls == ["_extract_info"]

    async def test_search_returns_empty_when_ytdlp_exceeds_timeout(self) -> None:
        async def slow_to_thread(func: object, *args: object, **kwargs: object) -> object:
            await asyncio.sleep(1)
            return {"entries": []}

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.to_thread", side_effect=slow_to_thread),
        ):
            adapter = YouTubeAdapter(search_timeout_sec=0.01)
            results = await adapter.search(SearchRequest(query="test"))

        assert results == []
