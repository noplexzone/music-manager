from __future__ import annotations

import re

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_first_run_owner_setup_login_and_authorization(
    unauthenticated_client: AsyncClient,
) -> None:
    client = unauthenticated_client
    assert (await client.get("/login")).status_code == 307

    weak = await client.post("/api/auth/setup", json={"username": "owner", "password": "short"})
    assert weak.status_code == 422

    setup = await client.post(
        "/api/auth/setup",
        json={"username": "owner", "password": "Correct-Horse-Battery-Staple-42"},
    )
    assert setup.status_code == 201
    assert setup.json()["role"] == "owner"
    assert "session" in client.cookies
    csrf = setup.json()["csrf_token"]

    assert (
        await client.post(
            "/jobs",
            json={"source": "youtube", "query": "test"},
            headers={"X-CSRF-Token": "wrong"},
        )
    ).status_code == 403

    created = await client.post(
        "/jobs",
        json={"source": "youtube", "query": "test"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    assert (
        await client.post(
            "/api/auth/setup", json={"username": "x", "password": "Long-Enough-Password-42"}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_login_abuse_controls_and_no_password_hash_disclosure(
    unauthenticated_client: AsyncClient,
) -> None:
    client = unauthenticated_client
    await client.post(
        "/api/auth/setup",
        json={"username": "owner", "password": "Correct-Horse-Battery-Staple-42"},
    )
    await client.post("/api/auth/logout", headers={"X-CSRF-Token": client.cookies["csrf"]})

    for _ in range(5):
        response = await client.post(
            "/api/auth/login", json={"username": "owner", "password": "incorrect-password"}
        )
        assert response.status_code == 401
    blocked = await client.post(
        "/api/auth/login", json={"username": "owner", "password": "incorrect-password"}
    )
    assert blocked.status_code == 429
    assert not re.search(r"argon2|password_hash", blocked.text, re.IGNORECASE)
