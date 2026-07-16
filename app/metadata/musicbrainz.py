from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_MB_BASE = "https://musicbrainz.org/ws/2"
_RATE_SEMAPHORE = asyncio.Semaphore(1)
_RATE_DELAY = 1.1


@dataclass
class TrackMeta:
    mbid: str
    title: str
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: str | None = None
    disc: int | None = None
    disc_total: int | None = None
    track_no: int | None = None
    duration_ms: int | None = None


def _is_503(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 503


class MusicBrainzClient:
    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_MB_BASE,
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
        )

    async def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        async with _RATE_SEMAPHORE:
            async with self._client() as client:
                resp = await client.get(path, params=params)
            await asyncio.sleep(_RATE_DELAY)
        if resp.status_code == 503:
            resp.raise_for_status()
        return resp

    @retry(
        retry=retry_if_exception(_is_503),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _get_with_retry(self, path: str, params: dict[str, str]) -> httpx.Response:
        return await self._get(path, params)

    async def lookup_recording(self, mbid: str) -> TrackMeta | None:
        resp = await self._get_with_retry(
            f"/recording/{mbid}",
            {"inc": "artists releases artist-credits", "fmt": "json"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_recording(resp.json())

    async def search_recording(
        self, title: str, artist: str | None = None, album: str | None = None
    ) -> list[TrackMeta]:
        parts = [f'recording:"{title}"']
        if artist:
            parts.append(f'artist:"{artist}"')
        if album:
            parts.append(f'release:"{album}"')
        lucene = " AND ".join(parts)

        resp = await self._get_with_retry(
            "/recording",
            {"query": lucene, "limit": "10", "fmt": "json"},
        )
        resp.raise_for_status()
        recordings = resp.json().get("recordings", [])
        return [r for r in (_parse_recording(rec) for rec in recordings) if r is not None]


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def _parse_recording(data: dict[str, object]) -> TrackMeta | None:
    mbid = data.get("id")
    if not mbid:
        return None

    title: str = str(data.get("title") or "")
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    year: str | None = None
    disc: int | None = None
    disc_total: int | None = None
    track_no: int | None = None
    duration_ms: int | None = None

    credits = data.get("artist-credit", [])
    if credits and isinstance(credits, list):
        artist_parts = []
        for credit in credits:
            if isinstance(credit, dict):
                a = credit.get("artist", {})
                if isinstance(a, dict):
                    name = a.get("name")
                    if name:
                        artist_parts.append(str(name))
                joinphrase = credit.get("joinphrase", "")
                if joinphrase:
                    artist_parts.append(str(joinphrase))
        artist = "".join(artist_parts).strip() or None

    releases = data.get("releases", [])
    if releases and isinstance(releases, list):
        rel = releases[0]
        if isinstance(rel, dict):
            album = str(rel.get("title") or "") or None
            date = str(rel.get("date") or "")
            year = date[:4] if date else None

            media_list = rel.get("media", [])
            if media_list and isinstance(media_list, list):
                media = media_list[0]
                if isinstance(media, dict):
                    disc = media.get("position")
                    disc_total = rel.get("media-count")
                    track_list = media.get("track", [])
                    if track_list and isinstance(track_list, list):
                        track_no = track_list[0].get("number")
                        try:
                            track_no = _to_int(track_no)
                        except (ValueError, TypeError):
                            track_no = None

    raw_duration = data.get("length")
    if raw_duration is not None:
        try:
            duration_ms = _to_int(raw_duration)
        except (ValueError, TypeError):
            duration_ms = None

    album_artist = artist

    return TrackMeta(
        mbid=str(mbid),
        title=title,
        artist=artist,
        album_artist=album_artist,
        album=album,
        year=year,
        disc=_to_int(disc),
        disc_total=_to_int(disc_total),
        track_no=track_no,
        duration_ms=duration_ms,
    )
