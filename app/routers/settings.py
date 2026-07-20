from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, require_admin_read, require_mutation
from app.config import Settings, get_settings
from app.database import get_db
from app.models.auth import AppUser
from app.schemas.health import SourceStatus
from app.schemas.settings import SettingField, SettingsSaveRequest, SettingsTestRequest
from app.settings_service import (
    DEFAULT_SOURCE_PRIORITY,
    get_all_effective,
    get_runtime_settings,
    load_raw_db_values,
    resolve_for_probe,
    save_runtime_settings,
    save_settings,
)
from app.sources.prowlarr import ProwlarrAdapter
from app.sources.sabnzbd import SabnzbdAdapter
from app.sources.slskd import SlskdAdapter
from app.sources.tidal import TidalAdapter
from app.sources.youtube import YouTubeAdapter

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


async def _probe_provider(
    provider: str,
    url: str,
    key: str,
    cookies: str,
) -> SourceStatus:
    from app.sources.base import CapabilityState

    cap: CapabilityState
    if provider == "slskd":
        cap = await SlskdAdapter(url, key).health()
    elif provider == "prowlarr":
        cap = await ProwlarrAdapter(url, key).health()
    elif provider == "sabnzbd":
        cap = await SabnzbdAdapter(url, key).health()
    elif provider == "youtube":
        cap = await YouTubeAdapter(cookies).health()
    else:
        cap = CapabilityState(available=False, reason="Unknown provider")
    return SourceStatus(available=cap.available, reason=cap.reason, details=cap.extra)


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(
    request: Request,
    _admin: Annotated[AppUser, Depends(require_admin_read)],
    db: Annotated[AsyncSession, Depends(get_db)],
    env: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    effective = await get_all_effective(db, env)
    fields = {
        k: SettingField(
            value=v.value,
            configured=v.configured,
            locked_by_environment=v.locked_by_environment,
        )
        for k, v in effective.items()
    }
    runtime = await get_runtime_settings(db)
    return _get_templates(request).TemplateResponse(
        request,
        "settings.html",
        {
            "settings": fields,
            "runtime": runtime,
            "default_sources": DEFAULT_SOURCE_PRIORITY,
        },
    )


@router.post("/settings", response_class=HTMLResponse, include_in_schema=False)
async def save_runtime_settings_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[object, Depends(require_mutation)],
) -> RedirectResponse:
    form = await request.form()
    order = [str(v) for v in form.getlist("source_order")]
    enabled = {str(v) for v in form.getlist("source_enabled")}
    source_priority = [{"name": name, "enabled": name in enabled} for name in order]
    limit = int(str(form.get("free_text_result_limit", "10")) or "10")
    await save_runtime_settings(db, source_priority, limit)
    await db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.get("/api/settings", response_model=dict[str, SettingField])
async def get_settings_api(
    _admin: Annotated[AppUser, Depends(require_admin_read)],
    db: Annotated[AsyncSession, Depends(get_db)],
    env: Annotated[Settings, Depends(get_settings)],
) -> dict[str, SettingField]:
    effective = await get_all_effective(db, env)
    return {
        k: SettingField(
            value=v.value,
            configured=v.configured,
            locked_by_environment=v.locked_by_environment,
        )
        for k, v in effective.items()
    }


@router.post("/api/settings/test", response_model=SourceStatus)
async def test_provider(
    payload: SettingsTestRequest,
    _admin: Annotated[AppUser, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    env: Annotated[Settings, Depends(get_settings)],
) -> SourceStatus:
    raw_db = await load_raw_db_values(db, env.secret_key)

    def _r(key: str, supplied: str) -> str:
        return resolve_for_probe(key, supplied, env, raw_db)

    if payload.provider == "slskd":
        return await _probe_provider(
            "slskd",
            url=_r("slskd_url", payload.slskd_url),
            key=_r("slskd_api_key", payload.slskd_api_key),
            cookies="",
        )
    if payload.provider == "prowlarr":
        return await _probe_provider(
            "prowlarr",
            url=_r("prowlarr_url", payload.prowlarr_url),
            key=_r("prowlarr_api_key", payload.prowlarr_api_key),
            cookies="",
        )
    if payload.provider == "sabnzbd":
        return await _probe_provider(
            "sabnzbd",
            url=_r("sabnzbd_url", payload.sabnzbd_url),
            key=_r("sabnzbd_api_key", payload.sabnzbd_api_key),
            cookies="",
        )
    if payload.provider == "youtube":
        return await _probe_provider(
            "youtube",
            url="",
            key="",
            cookies=_r("ytdlp_cookies_file", payload.ytdlp_cookies_file),
        )
    if payload.provider == "tidal":
        cap = await TidalAdapter(
            _r("tidal_config_path", payload.tidal_config_path),
            _r("tidal_session_path", payload.tidal_session_path),
            _r("tidal_quality", payload.tidal_quality),
        ).health()
        return SourceStatus(available=cap.available, reason=cap.reason, details=cap.extra)
    return SourceStatus(available=False, reason="Unknown provider", details={})  # pragma: no cover


@router.post("/api/settings/save")
async def save_settings_api(
    payload: SettingsSaveRequest,
    _admin: Annotated[AppUser, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    env: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    raw_db = await load_raw_db_values(db, env.secret_key)

    def _current(key: str) -> str:
        return resolve_for_probe(key, "", env, raw_db)

    submitted_fields = payload.model_fields_set

    def _changed(key: str, submitted: str | None, *, secret: bool = False) -> bool:
        if key not in submitted_fields:
            return False
        if secret and not submitted:
            return False
        return (submitted or "") != _current(key)

    validation_errors: dict[str, str] = {}

    async def _backstop(
        provider: str,
        url_key: str,
        key_key: str,
        url_sub: str | None,
        key_sub: str | None,
    ) -> None:
        if not (_changed(url_key, url_sub) or _changed(key_key, key_sub, secret=True)):
            return
        eff_url = url_sub if url_sub is not None else _current(url_key)
        eff_key = key_sub or _current(key_key)
        if not (eff_url and eff_key):
            validation_errors[provider] = "URL and API key are required together"
            return
        status = await _probe_provider(provider, url=eff_url, key=eff_key, cookies="")
        if not status.available:
            validation_errors[provider] = status.reason or "Connection failed"

    await _backstop(
        "slskd", "slskd_url", "slskd_api_key", payload.slskd_url, payload.slskd_api_key
    )
    await _backstop(
        "prowlarr",
        "prowlarr_url",
        "prowlarr_api_key",
        payload.prowlarr_url,
        payload.prowlarr_api_key,
    )
    await _backstop(
        "sabnzbd",
        "sabnzbd_url",
        "sabnzbd_api_key",
        payload.sabnzbd_url,
        payload.sabnzbd_api_key,
    )

    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={"validation_errors": validation_errors},
        )

    updates = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    await save_settings(db, updates, env)
    return {"status": "saved"}
