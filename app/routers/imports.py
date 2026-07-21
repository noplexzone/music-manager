from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_mutation
from app.config import Settings
from app.database import get_db
from app.models.import_plan import ImportPlan
from app.models.release import Release
from app.services.library_import import (
    ImportExecutionError,
    execute_release_import,
    plan_release_import,
)
from app.settings_service import effective_settings_dep

router = APIRouter(prefix="/imports", dependencies=[Depends(get_current_user)])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


def _plan_dict(plan: ImportPlan) -> dict[str, object]:
    return {
        "id": plan.id,
        "release_id": plan.release_id,
        "track_id": plan.track_id,
        "source_path": plan.source_path,
        "staging_path": plan.staging_path,
        "destination_path": plan.destination_path,
        "destination_temp_path": plan.destination_temp_path,
        "planned_operations": plan.planned_operations_json,
        "collision_state": plan.collision_state.value,
        "tag_verification_state": plan.tag_verification_state.value,
        "status": plan.status.value,
        "error_detail": plan.error_detail,
        "rollback_detail": plan.rollback_detail,
    }


@router.get("/plans")
async def list_import_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, object]]:
    result = await db.execute(select(ImportPlan).order_by(ImportPlan.created_at.desc()).limit(200))
    return [_plan_dict(plan) for plan in result.scalars().all()]


@router.post("/releases/{release_id}/plan")
async def plan_release(
    release_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    _user: Annotated[object, Depends(require_mutation)],
) -> list[dict[str, object]]:
    release = await db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    plans = await plan_release_import(
        db, release, library_root=settings.library_root, naming_template=settings.naming_template
    )
    return [_plan_dict(plan) for plan in plans]


@router.post("/releases/{release_id}/execute")
async def execute_release(
    release_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    _user: Annotated[object, Depends(require_mutation)],
) -> list[dict[str, object]]:
    release = await db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    try:
        plans = await execute_release_import(db, release, library_root=settings.library_root)
    except ImportExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return [_plan_dict(plan) for plan in plans]


@router.get("/ui/releases/{release_id}/plan", include_in_schema=False)
async def plan_release_from_review_get(release_id: int) -> RedirectResponse:
    del release_id
    return RedirectResponse("/imports/ui/review", status_code=307)


@router.post("/ui/releases/{release_id}/plan", response_class=RedirectResponse)
async def plan_release_from_review(
    release_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    _user: Annotated[object, Depends(require_mutation)],
) -> RedirectResponse:
    release = await db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    await plan_release_import(
        db, release, library_root=settings.library_root, naming_template=settings.naming_template
    )
    return RedirectResponse("/imports/ui/review", status_code=303)


@router.get("/ui/releases/{release_id}/execute", include_in_schema=False)
async def execute_release_from_review_get(release_id: int) -> RedirectResponse:
    del release_id
    return RedirectResponse("/imports/ui/review", status_code=307)


@router.post("/ui/releases/{release_id}/execute", response_class=RedirectResponse)
async def execute_release_from_review(
    release_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    _user: Annotated[object, Depends(require_mutation)],
) -> RedirectResponse:
    release = await db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    try:
        await execute_release_import(db, release, library_root=settings.library_root)
    except ImportExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse("/imports/ui/review", status_code=303)


@router.get("/ui/review", response_class=HTMLResponse)
async def import_review_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    templates = _get_templates(request)
    releases_result = await db.execute(
        select(Release).order_by(Release.created_at.desc()).limit(100)
    )
    plans_result = await db.execute(
        select(ImportPlan).order_by(ImportPlan.created_at.desc()).limit(200)
    )
    return templates.TemplateResponse(
        request,
        "imports.html",
        {
            "releases": list(releases_result.scalars().all()),
            "plans": list(plans_result.scalars().all()),
        },
    )
