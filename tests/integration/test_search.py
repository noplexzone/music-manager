from __future__ import annotations

from httpx import AsyncClient


async def test_search_returns_200_with_empty_sources(client: AsyncClient) -> None:
    resp = await client.post(
        "/search",
        json={"query": "Beethoven Symphony", "sources": []},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "source_states" in data


async def test_search_with_unknown_source_excluded(client: AsyncClient) -> None:
    resp = await client.post(
        "/search",
        json={"query": "test", "sources": ["nonexistent"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []


async def test_explicit_tidal_search_reports_unconfigured_profile(client: AsyncClient) -> None:
    resp = await client.post("/search", json={"query": "test", "sources": ["tidal"]})
    assert resp.status_code == 200
    state = resp.json()["source_states"]["tidal"]
    assert state["available"] is False
    assert state["details"]["code"] == "profile_unconfigured"


async def test_search_unconfigured_sources_gracefully_degrade(client: AsyncClient) -> None:
    resp = await client.post(
        "/search",
        json={"query": "test query", "sources": ["slskd", "prowlarr"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    for _name, state in data["source_states"].items():
        assert "available" in state


async def test_search_rejects_empty_query(client: AsyncClient) -> None:
    resp = await client.post("/search", json={"query": "", "sources": []})
    assert resp.status_code == 422


async def test_naming_preview_endpoint(client: AsyncClient) -> None:
    resp = await client.post(
        "/naming/preview",
        json={
            "title": "Bohemian Rhapsody",
            "album_artist": "Queen",
            "album": "A Night at the Opera",
            "year": "1975",
            "track_no": 11,
            "ext": "flac",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "rendered_path" in data
    assert "Bohemian Rhapsody" in data["rendered_path"]
    assert data["rendered_path"].endswith(".flac")
