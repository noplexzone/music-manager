from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_mutation
from app.database import get_db
from app.jobs.runner import run_job
from app.models.job import Job, JobStatus
from app.schemas.job import JobCreate, JobRead, JobSource, SelectedResultPayload

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)
_ALLOWED_JOB_SOURCES: set[JobSource] = {"slskd", "prowlarr", "youtube"}


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


def _selected_json(payload: SelectedResultPayload | None) -> str | None:
    return payload.model_dump_json() if payload is not None else None


@router.post("/jobs", response_model=JobRead, status_code=201)
async def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[object, Depends(require_mutation)],
) -> Job:
    job = Job(
        source=payload.source,
        query=payload.query,
        status=JobStatus.pending,
        selected_result_json=_selected_json(payload.selected_result),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    background_tasks.add_task(run_job, job.id)
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


@router.get("/downloads", response_class=HTMLResponse, include_in_schema=False)
async def downloads_page(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> HTMLResponse:
    templates = _get_templates(request)
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
    downloads = list(result.scalars().all())
    return templates.TemplateResponse(
        request, "downloads.html", {"downloads": downloads, "jobs": downloads}
    )


@router.get("/jobs/ui/list", include_in_schema=False)
async def old_jobs_page() -> RedirectResponse:
    return RedirectResponse("/downloads", status_code=308)


@router.post("/jobs/ui/create", response_class=HTMLResponse, include_in_schema=False)
@router.post("/downloads/create", response_class=HTMLResponse, include_in_schema=False)
async def create_job_ui(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[object, Depends(require_mutation)],
) -> RedirectResponse:
    form = await request.form()
    source = str(form.get("source", "slskd")).strip()
    query = str(form.get("query", "")).strip()
    selected_raw = str(form.get("selected_result", "")).strip()
    selected: SelectedResultPayload | None = None
    if selected_raw:
        try:
            selected = SelectedResultPayload.model_validate(json.loads(selected_raw))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Rejected invalid selected result payload from UI")
            return RedirectResponse("/downloads", status_code=303)
    if source not in _ALLOWED_JOB_SOURCES:
        logger.warning("Rejected unsupported download source from UI: %s", source)
        return RedirectResponse("/downloads", status_code=303)
    if not query and selected is None:
        return RedirectResponse("/downloads", status_code=303)
    job = Job(
        source=source,
        query=query or (selected.title if selected is not None else ""),
        status=JobStatus.pending,
        selected_result_json=_selected_json(selected),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    background_tasks.add_task(run_job, job.id)
    return RedirectResponse("/downloads", status_code=303)
