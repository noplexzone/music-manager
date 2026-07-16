from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs.runner import run_job
from app.models.job import Job, JobStatus
from app.schemas.job import JobCreate, JobRead

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


@router.post("/jobs", response_model=JobRead, status_code=201)
async def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Job:
    job = Job(source=payload.source, query=payload.query, status=JobStatus.pending)
    db.add(job)
    await db.flush()
    await db.refresh(job)
    background_tasks.add_task(run_job, job.id, db)
    return job


@router.get("/jobs", response_model=list[JobRead])
async def list_jobs(
    db: Annotated[AsyncSession, Depends(get_db)],
    status: JobStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Job]:
    q = select(Job).order_by(Job.created_at.desc()).offset(offset).limit(limit)
    if status is not None:
        q = q.where(Job.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: int, db: Annotated[AsyncSession, Depends(get_db)]) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/ui/list", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    templates = _get_templates(request)
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
    jobs = list(result.scalars().all())
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs})


@router.post("/jobs/ui/create", response_class=HTMLResponse)
async def create_job_ui(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    form = await request.form()
    source = str(form.get("source", "slskd")).strip()
    query = str(form.get("query", "")).strip()

    if not query:
        return RedirectResponse("/jobs/ui/list", status_code=303)

    job = Job(source=source, query=query, status=JobStatus.pending)
    db.add(job)
    await db.flush()
    await db.refresh(job)
    background_tasks.add_task(run_job, job.id, db)
    return RedirectResponse("/jobs/ui/list", status_code=303)
