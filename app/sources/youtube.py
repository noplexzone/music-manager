from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import CapabilityState

logger = logging.getLogger(__name__)

_MAX_SEARCH_RESULTS = 20
_DEFAULT_SEARCH_TIMEOUT_SEC = 30.0
_YTDLP_SOCKET_TIMEOUT_SEC = 15.0


def _ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except ImportError:
        return False


class YouTubeAdapter:
    name = "youtube"

    def __init__(
        self, cookies_file: str = "", search_timeout_sec: float = _DEFAULT_SEARCH_TIMEOUT_SEC
    ) -> None:
        self._cookies_file = cookies_file
        self._search_timeout_sec = search_timeout_sec

    async def health(self) -> CapabilityState:
        if _ytdlp_available():
            return CapabilityState(available=True)
        return CapabilityState(available=False, reason="yt-dlp is not installed")

    async def search(self, query: SearchRequest) -> list[SearchResult]:
        if not _ytdlp_available():
            return []

        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "default_search": "ytsearch",
            "socket_timeout": _YTDLP_SOCKET_TIMEOUT_SEC,
        }
        if self._cookies_file:
            ydl_opts["cookiefile"] = self._cookies_file

        search_url = f"ytsearch{_MAX_SEARCH_RESULTS}:{query.query}"

        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._extract_info, ydl_opts, search_url),
                timeout=self._search_timeout_sec,
            )
        except TimeoutError:
            logger.warning("YouTube search timed out after %.1f seconds", self._search_timeout_sec)
            return []
        except Exception as exc:
            logger.warning("YouTube search failed: %s", exc)
            return []

        entries: list[dict[str, Any]] = info.get("entries", []) if info else []
        results: list[SearchResult] = []
        for entry in entries:
            if not entry:
                continue
            duration = entry.get("duration")
            results.append(
                SearchResult(
                    source="youtube",
                    title=entry.get("title"),
                    artist=entry.get("channel") or entry.get("uploader"),
                    duration_sec=int(duration) if duration is not None else None,
                    url=entry.get("url") or entry.get("webpage_url"),
                    metadata={
                        "view_count": entry.get("view_count"),
                        "upload_date": entry.get("upload_date"),
                        "channel": entry.get("channel"),
                        "video_id": entry.get("id"),
                    },
                )
            )
        return results

    def _extract_info(self, ydl_opts: dict[str, Any], search_url: str) -> dict[str, Any]:
        import yt_dlp

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
        return info if isinstance(info, dict) else {}
