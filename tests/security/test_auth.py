from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

import app.auth as auth


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/search", {"json": {"query": "test", "sources": ["nonexistent"]}}),
        ("get", "/search", {}),
        ("post", "/search/ui", {"data": {"query": ""}}),
        ("get", "/tracks", {}),
        ("get", "/tracks/1", {}),
        ("get", "/tracks/1/ui", {}),
    ],
)
@pytest.mark.asyncio
async def test_search_and_track_routes_require_authentication(
    unauthenticated_client: AsyncClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    response = await unauthenticated_client.request(method, path, **kwargs)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "expected_status"),
    [
        ("post", "/search", {"json": {"query": "test", "sources": ["nonexistent"]}}, 200),
        ("get", "/search", {}, 200),
        ("post", "/search/ui", {"data": {"query": ""}}, 200),
        ("get", "/tracks", {}, 200),
        ("get", "/tracks/1", {}, 404),
        ("get", "/tracks/1/ui", {}, 404),
    ],
)
@pytest.mark.asyncio
async def test_authenticated_user_retains_search_and_track_read_access(
    client: AsyncClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
    expected_status: int,
) -> None:
    response = await client.request(method, path, **kwargs)

    assert response.status_code == expected_status


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


def test_login_attempt_cleanup_removes_expired_high_cardinality_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    monkeypatch.setattr(auth.time, "monotonic", lambda: now)
    auth._attempts.clear()

    for index in range(1_000):
        auth.record_login_failure(f"attacker-{index}:username-{index}")

    assert len(auth._attempts) == 1_000

    now += auth._WINDOW_SECONDS + 1
    auth.check_login_allowed("legitimate-client:owner")

    assert list(auth._attempts) == []


def test_login_attempt_store_evicts_oldest_active_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth.time, "monotonic", lambda: 1_000.0)
    monkeypatch.setattr(auth, "_MAX_ATTEMPT_KEYS", 3)
    auth._attempts.clear()

    for index in range(4):
        auth.record_login_failure(f"attacker-{index}:username-{index}")

    assert list(auth._attempts) == [
        "attacker-1:username-1",
        "attacker-2:username-2",
        "attacker-3:username-3",
    ]
