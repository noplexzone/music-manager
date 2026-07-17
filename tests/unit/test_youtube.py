from __future__ import annotations

import asyncio
import json
import signal
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.search import SearchRequest
from app.sources.youtube import ProviderError, YouTubeAdapter


class TestYouTubeHealth:
    async def test_health_available_when_ytdlp_installed(self) -> None:
        process = MagicMock(returncode=0)
        process.communicate = AsyncMock(
            return_value=(json.dumps({"formats": [{"acodec": "opus"}]}).encode(), b"")
        )
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
        ):
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
        process = MagicMock(returncode=0)
        process.communicate = AsyncMock(
            return_value=(json.dumps({"formats": [{"acodec": "opus"}]}).encode(), b"")
        )
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube._ytdlp_version", return_value="2026.7.1"),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
        ):
            state = await YouTubeAdapter().health()
        assert state.extra == {
            "code": "ok",
            "version": "2026.7.1",
            "cookies": "not_configured",
            "auth": "unprobed",
            "throttling": "not_detected",
            "audio_formats": "available",
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

    async def test_health_reports_rate_limit_without_raw_stderr(self) -> None:
        process = MagicMock(returncode=1)
        process.communicate = AsyncMock(return_value=(b"", b"HTTP Error 429 token=secret"))
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
        ):
            state = await YouTubeAdapter().health()
        assert state.available is False
        assert state.extra["code"] == "rate_limited"
        assert state.extra["throttling"] == "rate_limited"
        assert "secret" not in (state.reason or "")

    @pytest.mark.parametrize(
        ("codec", "expected_available"),
        [
            ("", False),
            ("   ", False),
            ("NoNe", False),
            ("NONE", False),
            (None, False),
            (0, False),
            (False, False),
            ({"name": "opus"}, False),
            (["opus"], False),
            ("opus", True),
        ],
    )
    async def test_health_requires_normalized_nonempty_audio_codec(
        self, codec: object, expected_available: bool
    ) -> None:
        process = MagicMock(returncode=0)
        process.communicate = AsyncMock(
            return_value=(json.dumps({"formats": [{"acodec": codec}]}).encode(), b"")
        )
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
        ):
            state = await YouTubeAdapter().health()
        assert state.available is expected_available
        assert state.extra["code"] == ("ok" if expected_available else "format_unavailable")

    async def test_health_rejects_expired_cookies(self, tmp_path: Path) -> None:
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            f".youtube.com\tTRUE\t/\tTRUE\t{int(time.time()) - 60}\tSID\texpired\n"
        )
        with patch("app.sources.youtube._ytdlp_available", return_value=True):
            state = await YouTubeAdapter(str(cookie_file)).health()
        assert state.available is False
        assert state.extra["code"] == "cookies_invalid_or_expired"
        assert state.extra["auth"] == "not_probed"

    async def test_public_probe_does_not_claim_cookie_auth_health(self, tmp_path: Path) -> None:
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            f".youtube.com\tTRUE\t/\tTRUE\t{int(time.time()) + 3600}\tSID\tsecret\n"
        )
        process = MagicMock(returncode=0)
        process.communicate = AsyncMock(
            return_value=(json.dumps({"formats": [{"acodec": "opus"}]}).encode(), b"")
        )
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
        ):
            state = await YouTubeAdapter(str(cookie_file)).health()
        assert state.available is True
        assert state.extra["auth"] == "unprobed"


class TestYouTubeAcquisition:
    async def test_acquire_stages_verified_audio_with_sanitized_provenance(
        self, tmp_path: Path
    ) -> None:
        async def spawn(*args: object, **kwargs: object) -> MagicMock:
            template = Path(args[args.index("--output") + 1])
            artifact = Path(str(template).replace("%(ext)s", "m4a"))
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"audio")  # noqa: ASYNC240 - fake subprocess fixture
            process = MagicMock(pid=321, returncode=0)
            process.communicate = AsyncMock(
                return_value=(
                    json.dumps(
                        {"id": "dQw4w9WgXcQ", "format_id": "140", "ext": "m4a", "acodec": "mp4a"}
                    ).encode(),
                    b"",
                )
            )
            return process

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", side_effect=spawn),
            patch("app.sources.youtube._is_supported_audio", return_value=True),
        ):
            acquired = await YouTubeAdapter().acquire(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&token=secret", tmp_path
            )
        assert acquired.path == tmp_path / "youtube" / "dQw4w9WgXcQ" / "audio.m4a"
        assert acquired.path.read_bytes() == b"audio"
        assert acquired.provenance["video_id"] == "dQw4w9WgXcQ"
        assert acquired.provenance["format_id"] == "140"
        assert "secret" not in json.dumps(acquired.provenance)

    async def test_acquire_timeout_reaps_child_and_removes_partial(self, tmp_path: Path) -> None:
        process = MagicMock(pid=654, returncode=None)
        process.communicate = AsyncMock(side_effect=[asyncio.TimeoutError, (b"", b"")])
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", return_value=process),
            patch("app.sources.youtube.os.killpg") as killpg,
            pytest.raises(ProviderError) as caught,
        ):
            await YouTubeAdapter(search_timeout_sec=0.01).acquire(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path
            )
        assert caught.value.code == "timeout"
        killpg.assert_called_once_with(654, signal.SIGTERM)
        assert list((tmp_path / "youtube").glob("*.partial")) == []

    async def test_acquire_rejects_symlinked_staging_ancestor_without_escape(
        self, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        linked = tmp_path / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec") as spawn,
            pytest.raises(ProviderError) as caught,
        ):
            await YouTubeAdapter().acquire(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ", linked / "staging"
            )
        assert caught.value.code == "unsafe_staging"
        spawn.assert_not_called()
        assert list(outside.iterdir()) == []

    @pytest.mark.parametrize(
        ("info", "artifact_name", "artifact_data"),
        [
            ({"ext": "m4a", "acodec": "none"}, "audio.m4a", b"<html>no audio</html>"),
            ({"ext": "m4a", "acodec": "mp4a"}, "audio.m4a", b"corrupt"),
            ({"ext": "m4a", "acodec": "mp4a"}, "audio.webm", b"audio"),
        ],
    )
    async def test_acquire_rejects_invalid_or_metadata_mismatched_artifact(
        self, tmp_path: Path, info: dict[str, str], artifact_name: str, artifact_data: bytes
    ) -> None:
        async def spawn(*args: object, **kwargs: object) -> MagicMock:
            template = Path(args[args.index("--output") + 1])
            artifact = template.parent / artifact_name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(artifact_data)
            process = MagicMock(pid=321, returncode=0)
            process.communicate = AsyncMock(return_value=(json.dumps(info).encode(), b""))
            return process

        with (
            patch("app.sources.youtube._ytdlp_available", return_value=True),
            patch("app.sources.youtube.asyncio.create_subprocess_exec", side_effect=spawn),
            pytest.raises(ProviderError) as caught,
        ):
            await YouTubeAdapter().acquire("https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path)
        assert caught.value.code == "artifact_invalid"
        youtube_dir = tmp_path / "youtube"
        assert not (youtube_dir / "dQw4w9WgXcQ").exists()
        assert list(youtube_dir.glob("*.partial")) == []


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
