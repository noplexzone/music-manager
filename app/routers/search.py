from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.schemas.health import SourceStatus
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.sources.base import SourceAdapter
from app.sources.prowlarr import ProwlarrAdapter
from app.sources.slskd import SlskdAdapter
from app.sources.youtube import ProviderError, YouTubeAdapter

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_SOURCES = {"slskd", "prowlarr", "youtube"}
_TIDAL_REASON = (
    "TIDAL acquisition unavailable: no supported lawful authenticated external downloader is "
    "configured; requires an operator-provided backend authorized for permanent local downloads."
)


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


def _build_adapter(name: str, settings: Settings) -> SourceAdapter | None:
    if name == "slskd":
        return SlskdAdapter(settings.slskd_url, settings.slskd_api_key)
    if name == "prowlarr":
        return ProwlarrAdapter(settings.prowlarr_url, settings.prowlarr_api_key)
    if name == "youtube":
        return YouTubeAdapter(settings.ytdlp_cookies_file)
    return None


async def _search_source(
    name: str, settings: Settings, query: SearchRequest
) -> tuple[str, list[SearchResult], SourceStatus]:
    adapter = _build_adapter(name, settings)
    if adapter is None:
        return name, [], SourceStatus(
            available=False, reason="Unknown source", details={"code": "unknown_source"}
        )

    cap = await adapter.health()
    if not cap.available:
        return name, [], SourceStatus(
            available=False, reason=cap.reason, details=cap.extra
        )

    try:
        results = await adapter.search(query)
        return name, results, SourceStatus(available=True)
    except ProviderError as exc:
        logger.warning("Search on %s failed with code %s", name, exc.code)
        return name, [], SourceStatus(
            available=False, reason=exc.message, details=exc.details()
        )
    except Exception:
        logger.warning("Search on %s failed", name, exc_info=True)
        return name, [], SourceStatus(
            available=False,
            reason="Source search failed",
            details={"code": "search_failed", "operation": "search", "retryable": True},
        )


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    if req.sources == []:
        requested = sorted(_VALID_SOURCES)
    else:
        requested = [s for s in req.sources if s in _VALID_SOURCES]
    tidal_requested = "tidal" in req.sources

    tasks = [_search_source(name, settings, req) for name in requested]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[SearchResult] = []
    source_states: dict[str, SourceStatus] = {}
    if tidal_requested:
        source_states["tidal"] = SourceStatus(
            available=False,
            reason=_TIDAL_REASON,
            details={"code": "backend_not_configured"},
        )

    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            logger.warning("Search task raised: %s", outcome)
            continue
        name, results, state = outcome
        all_results.extend(results)
        source_states[name] = state

    return SearchResponse(results=all_results, source_states=source_states)


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request) -> HTMLResponse:
    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "search.html",
        {"results": None, "query": "", "error": None},
    )


@router.post("/search/ui", response_class=HTMLResponse)
async def search_ui(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    templates = _get_templates(request)
    form = await request.form()
    query_str = str(form.get("query", "")).strip()
    sources_raw = str(form.get("sources", "slskd,prowlarr,youtube"))
    sources = [s.strip() for s in sources_raw.split(",") if s.strip() in _VALID_SOURCES]

    if not query_str:
        return templates.TemplateResponse(
            request,
            "search.html",
            {"results": None, "query": "", "error": "Query is required"},
        )

    req = SearchRequest(query=query_str, sources=sources)
    tasks = [_search_source(name, settings, req) for name in (sources or sorted(_VALID_SOURCES))]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[SearchResult] = []
    source_states: dict[str, SourceStatus] = {}
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            continue
        name, results, state = outcome
        all_results.extend(results)
        source_states[name] = state

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "results": all_results,
            "source_states": source_states,
            "query": query_str,
            "error": None,
        },
    )
