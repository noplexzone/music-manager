from __future__ import annotations

from httpx import AsyncClient


async def test_create_job_returns_201(client: AsyncClient) -> None:
    resp = await client.post(
        "/jobs",
        json={"source": "youtube", "query": "Beethoven Moonlight Sonata"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source"] == "youtube"
    assert data["query"] == "Beethoven Moonlight Sonata"
    assert data["status"] == "pending"
    assert "id" in data


async def test_list_jobs(client: AsyncClient) -> None:
    await client.post("/jobs", json={"source": "slskd", "query": "test track"})
    resp = await client.get("/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


async def test_get_job_by_id(client: AsyncClient) -> None:
    create = await client.post("/jobs", json={"source": "prowlarr", "query": "Miles Davis"})
    job_id = create.json()["id"]
    resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


async def test_get_job_not_found(client: AsyncClient) -> None:
    resp = await client.get("/jobs/99999")
    assert resp.status_code == 404


async def test_list_tracks_empty(client: AsyncClient) -> None:
    resp = await client.get("/tracks")
    assert resp.status_code == 200
    assert resp.json() == []
