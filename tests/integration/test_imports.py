from __future__ import annotations

from httpx import AsyncClient


async def test_import_plans_endpoint_starts_empty(client: AsyncClient) -> None:
    resp = await client.get("/imports/plans")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_import_review_page_renders(client: AsyncClient) -> None:
    resp = await client.get("/imports/ui/review")
    assert resp.status_code == 200
    assert "Import review" in resp.text
    assert "No import plans yet" in resp.text
