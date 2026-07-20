from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_mutation
from app.database import get_db
from app.settings_service import (
    DEFAULT_SOURCE_PRIORITY,
    get_runtime_settings,
    save_runtime_settings,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> HTMLResponse:
    runtime = await get_runtime_settings(db)
    return _get_templates(request).TemplateResponse(
        request, "settings.html", {"settings": runtime, "default_sources": DEFAULT_SOURCE_PRIORITY}
    )


@router.post("/settings", response_class=HTMLResponse, include_in_schema=False)
async def save_settings_page(
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
