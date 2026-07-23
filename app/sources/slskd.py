from __future__ import annotations

import asyncio
import logging

import httpx

from app.http import request_with_retry
from app.metadata.filename_parse import compose_search_query, parse_filename
from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import CapabilityState
from app.sources.youtube import ProviderError

logger = logging.getLogger(__name__)

_SEARCH_POLL_INTERVAL = 1.5
_SEARCH_TIMEOUT_SEC = 60
_HTTP_TIMEOUT = httpx.Timeout(10.0)


class SlskdAdapter:
    name = "slskd"

    def __init__(
        self, base_url: str, api_key: str, search_timeout_sec: float = _SEARCH_TIMEOUT_SEC
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._search_timeout_sec = search_timeout_sec

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": self._api_key},
            timeout=_HTTP_TIMEOUT,
        )

    async def health(self) -> CapabilityState:
        if not self._base_url or not self._api_key:
            return CapabilityState(available=False, reason="slskd not configured")
        try:
            async with self._client() as client:
                resp = await request_with_retry(client, "GET", "/api/v0/application")
            if resp.status_code == 200:
                return CapabilityState(available=True)
            return CapabilityState(available=False, reason=f"HTTP {resp.status_code}")
        except Exception as exc:
            logger.warning("slskd health check failed: %s", exc)
            return CapabilityState(available=False, reason=str(exc))

    async def search(self, query: SearchRequest) -> list[SearchResult]:
        if not self._base_url or not self._api_key:
            return []
        async with self._client() as client:
            resp = await request_with_retry(
                client,
                "POST",
                "/api/v0/searches",
                json={
                    "searchText": compose_search_query(
                        query.query, query.artist, query.album, query.track
                    ),
                    "fileLimit": 100,
                },
            )
            resp.raise_for_status()
            search_id = resp.json().get("id") or resp.json().get("searchId", "")
            if not search_id:
                raise ProviderError(
                    "missing_search_id",
                    "slskd create-search response did not include an id",
                    "search",
                )

            elapsed = 0.0
            while elapsed < self._search_timeout_sec:
                await asyncio.sleep(_SEARCH_POLL_INTERVAL)
                elapsed += _SEARCH_POLL_INTERVAL
                state_resp = await request_with_retry(
                    client, "GET", f"/api/v0/searches/{search_id}"
                )
                if state_resp.status_code == 200:
                    state = state_resp.json()
                    if state.get("state") in ("Completed", "Stopped", "TimedOut"):
                        break

            files_resp = await request_with_retry(
                client, "GET", f"/api/v0/searches/{search_id}/responses"
            )
            if files_resp.status_code != 200:
                return []

            results: list[SearchResult] = []
            for response in files_resp.json():
                username = response.get("username", "")
                for f in response.get("files", []):
                    filename: str = f.get("filename", "")
                    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                    guess = parse_filename(filename)
                    results.append(
                        SearchResult(
                            source="slskd",
                            title=guess.title,
                            artist=guess.artist,
                            album=guess.album,
                            size_bytes=f.get("size"),
                            format=ext or None,
                            url=f"slskd://{username}/{filename}",
                            metadata={
                                "username": username,
                                "filename": filename,
                                "parse_confidence": guess.confidence,
                                "parse_hints": list(guess.hints),
                                "bit_rate": f.get("bitRate"),
                                "sample_rate": f.get("sampleRate"),
                            },
                        )
                    )
            return results

    async def enqueue(self, username: str, filename: str, size: int | None = None) -> str:
        if not username or not filename:
            raise ProviderError(
                "invalid_result", "slskd result is missing username or filename", "acquire"
            )
        payload: dict[str, object] = {"filename": filename}
        if size is not None:
            payload["size"] = size
        async with self._client() as client:
            resp = await request_with_retry(
                client, "POST", f"/api/v0/transfers/downloads/{username}", json=payload
            )
            resp.raise_for_status()
        data = resp.json() if resp.content else {}
        transfer_id = str(data.get("id") or data.get("transferId") or f"{username}:{filename}")
        return transfer_id

    async def downloads(self) -> list[dict[str, object]]:
        async with self._client() as client:
            resp = await request_with_retry(client, "GET", "/api/v0/transfers/downloads")
            resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else list(data.get("downloads", []))

    async def status(self, transfer_id: str) -> CapabilityState:
        for item in await self.downloads():
            item_id = str(
                item.get("id")
                or item.get("transferId")
                or f"{item.get('username')}:{item.get('filename')}"
            )
            if item_id == transfer_id:
                state = str(item.get("state") or item.get("status") or "queued").casefold()
                return CapabilityState(True, state, dict(item))
        return CapabilityState(False, "transfer not found", {"transfer_id": transfer_id})

    async def cancel(self, username: str, filename: str) -> None:
        async with self._client() as client:
            resp = await request_with_retry(
                client,
                "DELETE",
                f"/api/v0/transfers/downloads/{username}",
                json={"filename": filename},
            )
            resp.raise_for_status()
