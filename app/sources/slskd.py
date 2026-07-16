from __future__ import annotations

import asyncio
import logging

import httpx

from app.http import request_with_retry
from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import CapabilityState

logger = logging.getLogger(__name__)

_SEARCH_POLL_INTERVAL = 1.5
_SEARCH_TIMEOUT_SEC = 60
_HTTP_TIMEOUT = httpx.Timeout(10.0)


class SlskdAdapter:
    name = "slskd"

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

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
                json={"searchText": query.query, "fileLimit": 100},
            )
            resp.raise_for_status()
            search_id = resp.json().get("id") or resp.json().get("searchId", "")

            elapsed = 0.0
            while elapsed < _SEARCH_TIMEOUT_SEC:
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
                    results.append(
                        SearchResult(
                            source="slskd",
                            title=filename.rsplit("/", 1)[-1] if "/" in filename else filename,
                            size_bytes=f.get("size"),
                            format=ext or None,
                            url=f"slskd://{username}/{filename}",
                            metadata={
                                "username": username,
                                "filename": filename,
                                "bit_rate": f.get("bitRate"),
                                "sample_rate": f.get("sampleRate"),
                            },
                        )
                    )
            return results
