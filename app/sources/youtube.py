from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import CapabilityState

_MAX_SEARCH_RESULTS = 20
_DEFAULT_SEARCH_TIMEOUT_SEC = 30.0
_PROCESS_STOP_GRACE_SEC = 2.0
_YTDLP_SOCKET_TIMEOUT_SEC = 15


@dataclass(frozen=True)
class ProviderError(RuntimeError):
    code: str
    message: str
    operation: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.message

    def details(self) -> dict[str, object]:
        return {
            "code": self.code,
            "operation": self.operation,
            "retryable": self.retryable,
        }


def _ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except ImportError:
        return False


def _ytdlp_version() -> str:
    try:
        return version("yt-dlp")
    except PackageNotFoundError:
        return "unknown"


def _cookie_status(cookie_file: str) -> tuple[bool, str, str]:
    if not cookie_file:
        return (
            True,
            "not_configured",
            "Cookies are not configured; public search remains available",
        )
    path = Path(cookie_file)
    if not path.exists() or not path.is_file():
        return False, "cookies_missing", "Configured cookies file is missing"
    if not os.access(path, os.R_OK):
        return False, "cookies_unreadable", "Configured cookies file is not readable"
    try:
        with path.open(encoding="utf-8") as cookie_stream:
            header = cookie_stream.readline(256).strip()
    except (OSError, UnicodeError):
        return False, "cookies_unreadable", "Configured cookies file is not readable"
    if not header.startswith("# Netscape HTTP Cookie File"):
        return (
            False,
            "cookies_invalid_or_expired",
            "Configured cookies file is not valid Netscape format",
        )
    return True, "configured", "Cookies are configured"


def _classify_failure(stderr: bytes) -> ProviderError:
    text = stderr.decode("utf-8", errors="replace").casefold()
    if "sign in" in text or "login" in text or "authentication" in text:
        code, message, retryable = "auth_required", "YouTube authentication is required", False
    elif "rate limit" in text or "too many requests" in text or "http error 429" in text:
        code, message, retryable = (
            "rate_limited",
            "YouTube temporarily rate limited the request",
            True,
        )
    elif "requested format is not available" in text:
        code, message, retryable = (
            "format_unavailable",
            "Requested audio format is unavailable",
            False,
        )
    elif "cookie" in text and ("expired" in text or "invalid" in text):
        code, message, retryable = (
            "cookies_invalid_or_expired",
            "Configured YouTube cookies are invalid or expired",
            False,
        )
    else:
        code, message, retryable = "extractor_error", "YouTube extractor failed", True
    return ProviderError(code, message, "search", retryable)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.communicate(), timeout=_PROCESS_STOP_GRACE_SEC)
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.communicate()


class YouTubeAdapter:
    name = "youtube"

    def __init__(
        self, cookies_file: str = "", search_timeout_sec: float = _DEFAULT_SEARCH_TIMEOUT_SEC
    ) -> None:
        self._cookies_file = cookies_file
        self._search_timeout_sec = search_timeout_sec

    async def health(self) -> CapabilityState:
        if not _ytdlp_available():
            return CapabilityState(
                available=False,
                reason="yt-dlp is not installed",
                extra={"code": "ytdlp_missing", "cookies": "not_probed", "auth": "not_probed"},
            )
        valid, cookie_state, reason = _cookie_status(self._cookies_file)
        details: dict[str, object] = {
            "code": "ok" if valid else cookie_state,
            "version": _ytdlp_version(),
            "cookies": cookie_state,
            "auth": "not_probed",
        }
        return CapabilityState(available=valid, reason=None if valid else reason, extra=details)

    async def search(self, query: SearchRequest) -> list[SearchResult]:
        if not _ytdlp_available():
            raise ProviderError("ytdlp_missing", "yt-dlp is not installed", "search")
        valid, code, reason = _cookie_status(self._cookies_file)
        if not valid:
            raise ProviderError(code, reason, "search")

        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--flat-playlist",
            "--skip-download",
            "--no-warnings",
            "--socket-timeout",
            str(_YTDLP_SOCKET_TIMEOUT_SEC),
        ]
        if self._cookies_file:
            command.extend(["--cookies", self._cookies_file])
        command.append(f"ytsearch{_MAX_SEARCH_RESULTS}:{query.query}")
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._search_timeout_sec
            )
        except TimeoutError as exc:
            await _stop_process(process)
            raise ProviderError("timeout", "YouTube search timed out", "search", True) from exc
        except asyncio.CancelledError:
            await _stop_process(process)
            raise

        if process.returncode != 0:
            raise _classify_failure(stderr)
        try:
            info = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(
                "extractor_error", "YouTube extractor returned invalid data", "search"
            ) from exc
        if not isinstance(info, dict):
            raise ProviderError(
                "extractor_error", "YouTube extractor returned invalid data", "search"
            )
        return self._results(info)

    @staticmethod
    def _results(info: dict[str, Any]) -> list[SearchResult]:
        entries: list[dict[str, Any]] = info.get("entries", []) if info else []
        results: list[SearchResult] = []
        for entry in entries:
            if not entry:
                continue
            duration = entry.get("duration")
            video_id = entry.get("id")
            canonical_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
            results.append(
                SearchResult(
                    source="youtube",
                    title=entry.get("title"),
                    artist=entry.get("channel") or entry.get("uploader"),
                    duration_sec=int(duration) if duration is not None else None,
                    url=canonical_url,
                    metadata={
                        "view_count": entry.get("view_count"),
                        "upload_date": entry.get("upload_date"),
                        "channel": entry.get("channel"),
                        "video_id": video_id,
                        "extractor": entry.get("extractor") or "youtube",
                    },
                )
            )
        return results
