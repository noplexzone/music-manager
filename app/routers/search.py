from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings
from app.database import get_db
from app.schemas.health import SourceStatus
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.services.catalog_metadata import search_catalog_artists
from app.settings_service import effective_settings_dep, get_runtime_settings
from app.sources.base import SourceAdapter
from app.sources.prowlarr import ProwlarrAdapter
from app.sources.slskd import SlskdAdapter
from app.sources.tidal import TidalAdapter
from app.sources.youtube import ProviderError, YouTubeAdapter

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

_VALID_SOURCES = {"slskd", "prowlarr", "youtube", "tidal"}
_DEFAULT_SOURCES = {"slskd", "prowlarr", "youtube"}


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


def _build_adapter(name: str, settings: Settings) -> SourceAdapter | None:
    if name == "slskd":
        return SlskdAdapter(settings.slskd_url, settings.slskd_api_key)
    if name == "prowlarr":
        return ProwlarrAdapter(settings.prowlarr_url, settings.prowlarr_api_key)
    if name == "youtube":
        return YouTubeAdapter(settings.ytdlp_cookies_file)
    if name == "tidal":
        return TidalAdapter(
            settings.tidal_config_path,
            settings.tidal_session_path,
            settings.tidal_quality,
        )
    return None


async def _search_source(
    name: str, settings: Settings, query: SearchRequest
) -> tuple[str, list[SearchResult], SourceStatus]:
    adapter = _build_adapter(name, settings)
    if adapter is None:
        return (
            name,
            [],
            SourceStatus(
                available=False, reason="Unknown source", details={"code": "unknown_source"}
            ),
        )

    cap = await adapter.health()
    if not cap.available:
        return name, [], SourceStatus(available=False, reason=cap.reason, details=cap.extra)

    try:
        results = await adapter.search(query)
        return name, results, SourceStatus(available=True)
    except ProviderError as exc:
        logger.warning("Search on %s failed with code %s", name, exc.code)
        return name, [], SourceStatus(available=False, reason=exc.message, details=exc.details())
    except Exception:
        logger.warning("Search on %s failed", name)
        return (
            name,
            [],
            SourceStatus(
                available=False,
                reason="Source search failed",
                details={"code": "search_failed", "operation": "search", "retryable": True},
            ),
        )


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    runtime = await get_runtime_settings(db)
    if req.sources == []:
        requested = [s for s in runtime.enabled_sources if s in _VALID_SOURCES]
    else:
        requested = [s for s in req.sources if s in _VALID_SOURCES]
    tasks = [_search_source(name, settings, req) for name in requested]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[SearchResult] = []
    source_states: dict[str, SourceStatus] = {}

    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            logger.warning("Search task failed")
            continue
        name, results, state = outcome
        all_results.extend(results)
        source_states[name] = state

    priority = {name: index for index, name in enumerate(requested)}
    all_results.sort(key=lambda r: priority.get(r.source, 999))
    return SearchResponse(results=all_results, source_states=source_states)


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = "",
    tab: str = "catalog",
    provider: str = "all",
) -> HTMLResponse:
    templates = _get_templates(request)
    runtime = await get_runtime_settings(db)
    metadata_providers = runtime.enabled_metadata_providers
    requested = metadata_providers if provider == "all" else [provider]
    catalog_outcomes = []
    if q and metadata_providers:
        catalog_outcomes = await search_catalog_artists(settings, q, requested)
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "tab": tab,
            "catalog_query": q,
            "catalog_provider": provider,
            "metadata_providers": runtime.metadata_providers,
            "catalog_outcomes": catalog_outcomes,
            "metadata_enabled": metadata_providers,
            "results": None,
            "source_states": {},
            "query": "",
            "artist": "",
            "album": "",
            "track": "",
            "error": None,
        },
    )


@router.get("/search/ui", include_in_schema=False)
async def search_ui_get() -> RedirectResponse:
    return RedirectResponse("/search", status_code=307)


@router.post("/search/ui", response_class=HTMLResponse)
async def search_ui(
    request: Request,
    settings: Annotated[Settings, Depends(effective_settings_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    templates = _get_templates(request)
    form = await request.form()
    query_str = str(form.get("query", "")).strip()
    artist = str(form.get("artist", "")).strip()
    album = str(form.get("album", "")).strip()
    track = str(form.get("track", "")).strip()
    runtime = await get_runtime_settings(db)
    sources_raw = str(form.get("sources", ",".join(runtime.enabled_sources)))
    sources = [s.strip() for s in sources_raw.split(",") if s.strip() in _VALID_SOURCES]

    if not (query_str or artist or album or track):
        return templates.TemplateResponse(
            request,
            "search.html",
            {
                "tab": "advanced",
                "catalog_query": "",
                "catalog_provider": "all",
                "metadata_providers": runtime.metadata_providers,
                "catalog_outcomes": [],
                "metadata_enabled": runtime.enabled_metadata_providers,
                "results": None,
                "query": "",
                "artist": artist,
                "album": album,
                "track": track,
                "error": "At least one search field is required",
            },
        )

    req = SearchRequest(
        query=query_str,
        artist=artist or None,
        album=album or None,
        track=track or None,
        sources=sources,
    )
    ordered_sources = sources or [s for s in runtime.enabled_sources if s in _VALID_SOURCES]
    tasks = [_search_source(name, settings, req) for name in ordered_sources]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[SearchResult] = []
    source_states: dict[str, SourceStatus] = {}
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            continue
        name, results, state = outcome
        all_results.extend(results)
        source_states[name] = state
    priority = {name: index for index, name in enumerate(ordered_sources)}
    all_results.sort(key=lambda r: priority.get(r.source, 999))

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "tab": "advanced",
            "catalog_query": "",
            "catalog_provider": "all",
            "metadata_providers": runtime.metadata_providers,
            "catalog_outcomes": [],
            "metadata_enabled": runtime.enabled_metadata_providers,
            "results": all_results,
            "source_states": source_states,
            "query": query_str,
            "artist": artist,
            "album": album,
            "track": track,
            "error": None,
        },
    )
