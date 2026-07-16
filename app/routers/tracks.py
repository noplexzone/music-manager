from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.track import Track
from app.schemas.track import TrackRead

router = APIRouter()


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


@router.get("/tracks", response_model=list[TrackRead])
async def list_tracks(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Track]:
    q = (
        select(Track)
        .options(selectinload(Track.path_previews))
        .order_by(Track.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if job_id is not None:
        q = q.where(Track.job_id == job_id)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/tracks/{track_id}", response_model=TrackRead)
async def get_track(
    track_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Track:
    result = await db.execute(
        select(Track).options(selectinload(Track.path_previews)).where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@router.get("/tracks/{track_id}/ui", response_class=HTMLResponse)
async def track_detail_page(
    track_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    templates = _get_templates(request)
    result = await db.execute(
        select(Track).options(selectinload(Track.path_previews)).where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return templates.TemplateResponse(request, "track.html", {"track": track})
