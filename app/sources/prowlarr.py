from __future__ import annotations

import logging

import httpx

from app.http import request_with_retry
from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import CapabilityState

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(15.0)


class ProwlarrAdapter:
    name = "prowlarr"

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-Api-Key": self._api_key},
            timeout=_HTTP_TIMEOUT,
        )

    async def health(self) -> CapabilityState:
        if not self._base_url or not self._api_key:
            return CapabilityState(available=False, reason="prowlarr not configured")
        try:
            async with self._client() as client:
                resp = await request_with_retry(client, "GET", "/api/v1/health")
            if resp.status_code == 200:
                issues = resp.json() if isinstance(resp.json(), list) else []
                errors = [i for i in issues if i.get("type") == "error"]
                if errors:
                    return CapabilityState(
                        available=False, reason="; ".join(e.get("message", "") for e in errors)
                    )
                return CapabilityState(available=True)
            return CapabilityState(available=False, reason=f"HTTP {resp.status_code}")
        except Exception as exc:
            logger.warning("prowlarr health check failed: %s", exc)
            return CapabilityState(available=False, reason=str(exc))

    async def search(self, query: SearchRequest) -> list[SearchResult]:
        if not self._base_url or not self._api_key:
            return []
        async with self._client() as client:
            resp = await request_with_retry(
                client,
                "GET",
                "/api/v1/search",
                params={"query": query.query, "type": "search", "limit": 100},
            )
            resp.raise_for_status()

        results: list[SearchResult] = []
        for item in resp.json():
            download_url = item.get("downloadUrl")
            is_nzb = isinstance(download_url, str) and download_url.endswith(".nzb")
            results.append(
                SearchResult(
                    source="prowlarr",
                    title=item.get("title"),
                    size_bytes=item.get("size"),
                    format="nzb" if is_nzb else None,
                    url=download_url if is_nzb else None,
                    metadata={
                        "indexer": item.get("indexer"),
                        "seeders": item.get("seeders"),
                        "leechers": item.get("leechers"),
                        "grabs": item.get("grabs"),
                        "publish_date": item.get("publishDate"),
                    },
                )
            )
        return results
