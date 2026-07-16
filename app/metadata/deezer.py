from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.http import request_with_retry

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(10.0)


@dataclass
class DeezerTrack:
    deezer_id: str
    title: str
    artist: str | None = None
    album: str | None = None
    bpm: float | None = None
    gain: float | None = None
    preview_url: str | None = None
    explicit: bool = False
    rank: int | None = None
    duration_sec: int | None = None


class DeezerClient:
    def __init__(self, base_url: str = "https://api.deezer.com") -> None:
        self._base_url = base_url.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=_HTTP_TIMEOUT)

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
    )
    async def search_track(self, title: str, artist: str | None = None) -> list[DeezerTrack]:
        q = title
        if artist:
            q = f'track:"{title}" artist:"{artist}"'
        async with self._client() as client:
            resp = await request_with_retry(client, "GET", "/search", params={"q": q, "limit": 10})
            resp.raise_for_status()
        return [_parse_track(item) for item in resp.json().get("data", [])]

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
    )
    async def get_track(self, deezer_id: str) -> DeezerTrack | None:
        async with self._client() as client:
            resp = await request_with_retry(client, "GET", f"/track/{deezer_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_track(resp.json())


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def _parse_track(data: dict[str, object]) -> DeezerTrack:
    track_id = str(data.get("id", ""))
    title = str(data.get("title") or data.get("title_short") or "")
    artist = None
    album = None

    artist_data = data.get("artist")
    if isinstance(artist_data, dict):
        artist = str(artist_data.get("name") or "") or None

    album_data = data.get("album")
    if isinstance(album_data, dict):
        album = str(album_data.get("title") or "") or None

    bpm = data.get("bpm")
    gain = data.get("gain")
    preview = data.get("preview")
    duration = data.get("duration")
    explicit_flag = data.get("explicit_lyrics")
    rank = data.get("rank")

    return DeezerTrack(
        deezer_id=track_id,
        title=title,
        artist=artist,
        album=album,
        bpm=_to_float(bpm),
        gain=_to_float(gain),
        preview_url=str(preview) if preview else None,
        explicit=bool(explicit_flag),
        rank=_to_int(rank),
        duration_sec=_to_int(duration),
    )
