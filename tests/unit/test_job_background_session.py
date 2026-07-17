from __future__ import annotations

from fastapi import BackgroundTasks
from httpx import AsyncClient

from app.database import get_session_factory
from app.models.job import Job
from app.routers import jobs


async def test_create_job_schedules_runner_without_request_scoped_session(
    client: AsyncClient, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    scheduled: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def capture_add_task(
        self: BackgroundTasks, func: object, *args: object, **kwargs: object
    ) -> None:
        scheduled.append((func, args, kwargs))

    async def noop_run_job(job_id: int) -> None:
        return None

    mp.setattr(BackgroundTasks, "add_task", capture_add_task)
    mp.setattr(jobs, "run_job", noop_run_job)

    response = await client.post("/jobs", json={"source": "youtube", "query": "test"})

    assert response.status_code == 201
    assert scheduled == [(noop_run_job, (response.json()["id"],), {})]


async def test_background_runner_can_read_committed_job_before_response_finishes(
    client: AsyncClient, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    seen: list[bool] = []

    async def probe_run_job(job_id: int) -> None:
        factory = get_session_factory()
        async with factory() as session:
            seen.append(await session.get(Job, job_id) is not None)

    mp.setattr(jobs, "run_job", probe_run_job)

    response = await client.post("/jobs", json={"source": "youtube", "query": "test"})

    assert response.status_code == 201
    assert seen == [True]
