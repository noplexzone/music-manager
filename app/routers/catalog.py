from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_mutation
from app.config import Settings
from app.database import get_db
from app.jobs.runner import run_job
from app.models.catalog_entities import CatalogAlbum, CatalogArtist
from app.models.job import Job, JobStatus
from app.services.catalog import (
    get_artist_detail,
    get_artists_page,
    get_library_stats,
    list_distinct_formats,
    list_distinct_sources,
    list_library_tracks,
)
from app.services.catalog_metadata import (
    fetch_and_store_album,
    fetch_and_store_discography,
    open_catalog_artist,
)
from app.settings_service import effective_settings_dep, get_runtime_settings

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


@router.get("/artists/catalog/open", response_class=HTMLResponse)
async def open_catalog_artist_page(
    provider: str,
    provider_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
) -> RedirectResponse:
    artist = await open_catalog_artist(db, settings, provider, provider_id)
    await db.commit()
    return RedirectResponse(f"/artists/catalog/{artist.id}", status_code=303)


@router.get("/artists/catalog/{artist_id}", response_class=HTMLResponse)
async def catalog_artist_page(
    request: Request,
    artist_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    release_type: str = "",
) -> HTMLResponse:
    artist = await db.get(CatalogArtist, artist_id)
    if artist is None:
        raise HTTPException(status_code=404, detail="Catalog artist not found")
    try:
        await fetch_and_store_discography(db, settings, artist)
        await db.commit()
    except Exception:
        await db.rollback()
    result = await db.execute(
        select(CatalogArtist)
        .where(CatalogArtist.id == artist_id)
        .options(selectinload(CatalogArtist.albums))
    )
    artist = result.scalar_one()
    albums = sorted(
        artist.albums,
        key=lambda album: (album.year or "0000", album.title),
        reverse=True,
    )
    if release_type:
        albums = [
            a for a in albums if (a.release_type or "").casefold() == release_type.casefold()
        ]
    release_types = sorted({a.release_type for a in artist.albums if a.release_type})
    return _templates(request).TemplateResponse(
        request,
        "catalog_artist.html",
        {
            "artist": artist,
            "albums": albums,
            "release_types": release_types,
            "release_type": release_type,
        },
    )


@router.get("/albums/{album_id}", response_class=HTMLResponse)
async def catalog_album_page(
    request: Request,
    album_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(effective_settings_dep)],
) -> HTMLResponse:
    result = await db.execute(
        select(CatalogAlbum)
        .where(CatalogAlbum.id == album_id)
        .options(selectinload(CatalogAlbum.artist), selectinload(CatalogAlbum.tracks))
    )
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail="Catalog album not found")
    try:
        album = await fetch_and_store_album(db, settings, album)
        await db.commit()
    except Exception:
        await db.rollback()
    result = await db.execute(
        select(CatalogAlbum)
        .where(CatalogAlbum.id == album_id)
        .options(selectinload(CatalogAlbum.artist), selectinload(CatalogAlbum.tracks))
    )
    album = result.scalar_one()
    return _templates(request).TemplateResponse(request, "catalog_album.html", {"album": album})


@router.post("/albums/{album_id}/download", include_in_schema=False)
async def download_catalog_album(
    album_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[object, Depends(require_mutation)],
) -> RedirectResponse:
    result = await db.execute(
        select(CatalogAlbum)
        .where(CatalogAlbum.id == album_id)
        .options(selectinload(CatalogAlbum.artist))
    )
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail="Catalog album not found")
    runtime = await get_runtime_settings(db)
    source = runtime.enabled_sources[0] if runtime.enabled_sources else "slskd"
    query = f"{album.artist.name} {album.title}".strip()
    job = Job(source=source, query=query, status=JobStatus.pending, catalog_album_id=album.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    background_tasks.add_task(run_job, job.id)
    return RedirectResponse("/downloads", status_code=303)


@router.post("/albums/{album_id}/tracks/{track_id}/download", include_in_schema=False)
async def download_catalog_track(
    album_id: int,
    track_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[object, Depends(require_mutation)],
) -> RedirectResponse:
    result = await db.execute(
        select(CatalogAlbum)
        .where(CatalogAlbum.id == album_id)
        .options(selectinload(CatalogAlbum.artist), selectinload(CatalogAlbum.tracks))
    )
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail="Catalog album not found")
    track = next((t for t in album.tracks if t.id == track_id), None)
    if track is None:
        raise HTTPException(status_code=404, detail="Catalog track not found")
    runtime = await get_runtime_settings(db)
    source = runtime.enabled_sources[0] if runtime.enabled_sources else "slskd"
    query = f"{album.artist.name} {track.title}".strip()
    job = Job(
        source=source,
        query=query,
        status=JobStatus.pending,
        catalog_album_id=album.id,
        catalog_track_id=track.id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    background_tasks.add_task(run_job, job.id)
    return RedirectResponse("/downloads", status_code=303)
