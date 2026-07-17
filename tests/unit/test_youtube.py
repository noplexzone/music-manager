from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.search import SearchRequest
from app.sources.youtube import ProviderError, YouTubeAdapter


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

    async def test_health_reports_version_and_unconfigured_cookies(self) -> None:
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube._ytdlp_version", return_value="2026.7.1"),
        ):
            state = await YouTubeAdapter().health()
        assert state.extra == {
            "code": "ok",
            "version": "2026.7.1",
            "cookies": "not_configured",
            "auth": "not_probed",
        }

    async def test_health_rejects_missing_cookie_file_without_exposing_path(
        self, tmp_path: Path
    ) -> None:
        secret_path = tmp_path / "secret-cookies.txt"
        with patch("app.sources.youtube._ytdlp_available", return_value=True):
            state = await YouTubeAdapter(str(secret_path)).health()
        assert state.available is False
        assert state.extra["code"] == "cookies_missing"
        assert str(secret_path) not in (state.reason or "")


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
        process = MagicMock(pid=123, returncode=0)
        process.communicate = AsyncMock(return_value=(json.dumps(mock_info).encode(), b""))

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
        ):
            adapter = YouTubeAdapter()
            results = await adapter.search(SearchRequest(query="Never Gonna Give You Up"))

        assert len(results) == 1
        assert results[0].source == "youtube"
        assert results[0].duration_sec == 213
        assert results[0].title is not None

    async def test_search_fails_when_ytdlp_missing(self) -> None:
        with patch("app.sources.youtube._ytdlp_available", return_value=False):
            adapter = YouTubeAdapter()
            with pytest.raises(ProviderError, match="yt-dlp is not installed") as caught:
                await adapter.search(SearchRequest(query="test"))
        assert caught.value.code == "ytdlp_missing"

    async def test_search_runs_ytdlp_as_bounded_subprocess(self) -> None:
        process = MagicMock(pid=123)
        process.communicate = AsyncMock(return_value=(json.dumps({"entries": []}).encode(), b""))
        process.returncode = 0
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch(
                "app.sources.youtube.asyncio.create_subprocess_exec", return_value=process
            ) as spawn,
        ):
            results = await YouTubeAdapter().search(SearchRequest(query="test"))

        assert results == []
        assert spawn.call_args.kwargs["start_new_session"] is True
        assert "ytsearch20:test" in spawn.call_args.args

    async def test_search_kills_and_reaps_subprocess_on_timeout(self) -> None:
        process = MagicMock(pid=123, returncode=None)
        process.communicate = AsyncMock(side_effect=[asyncio.TimeoutError, (b"", b"")])
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
            patch("app.sources.youtube.os.killpg") as killpg,
        ):
            adapter = YouTubeAdapter(search_timeout_sec=0.01)
            with pytest.raises(ProviderError) as caught:
                await adapter.search(SearchRequest(query="test"))
        assert caught.value.code == "timeout"
        killpg.assert_called_once_with(123, signal.SIGTERM)
        assert process.communicate.await_count == 2

    async def test_search_kills_and_reaps_subprocess_on_cancellation(self) -> None:
        process = MagicMock(pid=456, returncode=None)
        process.communicate = AsyncMock(side_effect=[asyncio.CancelledError, (b"", b"")])
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
            patch("app.sources.youtube.os.killpg") as killpg,
            pytest.raises(asyncio.CancelledError),
        ):
            await YouTubeAdapter().search(SearchRequest(query="test"))
        killpg.assert_called_once_with(456, signal.SIGTERM)
        assert process.communicate.await_count == 2

    async def test_search_sanitizes_extractor_failure(self) -> None:
        process = MagicMock(pid=123, returncode=1)
        secret = b"ERROR /private/cookies.txt token=secret\nHTTP Error 429"
        process.communicate = AsyncMock(return_value=(b"", secret))
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
            pytest.raises(ProviderError) as caught,
        ):
            await YouTubeAdapter().search(SearchRequest(query="test"))
        assert caught.value.code == "rate_limited"
        assert "secret" not in caught.value.message
