from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.services.catalog import (
    get_artist_detail,
    get_artists_page,
    get_library_stats,
    list_distinct_formats,
    list_distinct_sources,
    list_library_tracks,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


@router.get("/library", response_class=HTMLResponse)
async def library_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = "",
    artist: str = "",
    album: str = "",
    source: str = "",
    fmt: str = "",
    sort: str = "added",
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=50, ge=1, le=200),
) -> HTMLResponse:
    stats = await get_library_stats(db)
    all_sources = await list_distinct_sources(db)
    all_formats = await list_distinct_formats(db)
    tracks = await list_library_tracks(
        db,
        q=q,
        artist=artist,
        album=album,
        source=source,
        fmt=fmt,
        sort=sort,
        page=page,
        per_page=per_page,
    )

    filter_params: dict[str, str] = {}
    if q:
        filter_params["q"] = q
    if artist:
        filter_params["artist"] = artist
    if album:
        filter_params["album"] = album
    if source:
        filter_params["source"] = source
    if fmt:
        filter_params["fmt"] = fmt
    filter_params["sort"] = sort
    filter_params["per_page"] = str(per_page)
    filter_qs = urlencode(filter_params)

    return _templates(request).TemplateResponse(
        request,
        "library.html",
        {
            "stats": stats,
            "tracks": tracks,
            "all_sources": all_sources,
            "all_formats": all_formats,
            "q": q,
            "filter_artist": artist,
            "filter_album": album,
            "filter_source": source,
            "filter_fmt": fmt,
            "sort": sort,
            "per_page": per_page,
            "filter_qs": filter_qs,
        },
    )


@router.get("/artists", response_class=HTMLResponse)
async def artists_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = "",
    sort: str = "name",
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=50, ge=1, le=200),
) -> HTMLResponse:
    artists = await get_artists_page(db, q=q, sort=sort, page=page, per_page=per_page)

    filter_params: dict[str, str] = {}
    if q:
        filter_params["q"] = q
    filter_params["sort"] = sort
    filter_params["per_page"] = str(per_page)
    filter_qs = urlencode(filter_params)

    return _templates(request).TemplateResponse(
        request,
        "artists.html",
        {
            "artists": artists,
            "q": q,
            "sort": sort,
            "per_page": per_page,
            "filter_qs": filter_qs,
        },
    )


@router.get("/artists/detail", response_class=HTMLResponse)
async def artist_detail_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    name: str = "",
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=50, ge=1, le=200),
) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Artist name is required")
    detail = await get_artist_detail(db, artist_name=name, page=page, per_page=per_page)
    return _templates(request).TemplateResponse(
        request,
        "artist_detail.html",
        {"detail": detail},
    )
