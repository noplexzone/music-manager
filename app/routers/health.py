from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas.health import HealthResponse, SourceStatus
from app.sources.base import SourceAdapter
from app.sources.prowlarr import ProwlarrAdapter
from app.sources.sabnzbd import SabnzbdAdapter
from app.sources.slskd import SlskdAdapter
from app.sources.tidal_status import TIDAL_STATUS
from app.sources.youtube import YouTubeAdapter

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_adapters(settings: Settings) -> dict[str, SourceAdapter]:
    return {
        "slskd": SlskdAdapter(settings.slskd_url, settings.slskd_api_key),
        "prowlarr": ProwlarrAdapter(settings.prowlarr_url, settings.prowlarr_api_key),
        "sabnzbd": SabnzbdAdapter(settings.sabnzbd_url, settings.sabnzbd_api_key),
        "youtube": YouTubeAdapter(settings.ytdlp_cookies_file),
    }


async def _check_db(db: AsyncSession) -> bool:
    try:
        await db.execute(text("CREATE TEMP TABLE IF NOT EXISTS health_write_check (id INTEGER)"))
        await db.execute(text("INSERT INTO health_write_check (id) VALUES (1)"))
        return True
    except Exception as exc:
        logger.warning("DB write check failed: %s", exc)
        return False


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HealthResponse:
    adapters = _build_adapters(settings)

    checks = await asyncio.gather(
        *[adapter.health() for adapter in adapters.values()],
        return_exceptions=True,
    )

    sources: dict[str, SourceStatus] = {}
    for name, result in zip(adapters.keys(), checks, strict=True):
        if isinstance(result, BaseException):
            sources[name] = SourceStatus(
                available=False,
                reason="Source health check failed",
                details={"code": "health_check_failed"},
            )
        else:
            sources[name] = SourceStatus(
                available=result.available, reason=result.reason, details=result.extra
            )

    sources["tidal"] = TIDAL_STATUS

    db_writable = await _check_db(db)

    all_available = all(s.available for name, s in sources.items() if name != "tidal")
    none_available = not any(s.available for name, s in sources.items() if name != "tidal")

    if not db_writable or none_available:
        status = "down"
    elif all_available and db_writable:
        status = "ok"
    else:
        status = "degraded"

    return HealthResponse(status=status, sources=sources, db_writable=db_writable)


@router.get("/health/sources", response_model=dict[str, SourceStatus])
async def health_sources(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, SourceStatus]:
    adapters = _build_adapters(settings)

    checks = await asyncio.gather(
        *[adapter.health() for adapter in adapters.values()],
        return_exceptions=True,
    )

    sources: dict[str, SourceStatus] = {}
    for name, result in zip(adapters.keys(), checks, strict=True):
        if isinstance(result, BaseException):
            sources[name] = SourceStatus(
                available=False,
                reason="Source health check failed",
                details={"code": "health_check_failed"},
            )
        else:
            sources[name] = SourceStatus(
                available=result.available, reason=result.reason, details=result.extra
            )

    sources["tidal"] = TIDAL_STATUS
    return sources
