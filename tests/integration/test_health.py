from __future__ import annotations

from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_health_schema(client: AsyncClient) -> None:
    resp = await client.get("/health")
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("ok", "degraded", "down")
    assert "sources" in data
    assert isinstance(data["sources"], dict)


async def test_health_tidal_always_unavailable(client: AsyncClient) -> None:
    resp = await client.get("/health")
    data = resp.json()
    assert "tidal" in data["sources"]
    tidal = data["sources"]["tidal"]
    assert tidal["available"] is False
    assert tidal["details"]["code"] == "backend_not_configured"
    assert "lawful authenticated external downloader" in tidal["reason"]


async def test_health_sources_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/health/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "tidal" in data
    assert data["tidal"]["available"] is False


async def test_health_db_writable_key_present(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert "db_writable" in resp.json()


async def test_root_returns_200(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
