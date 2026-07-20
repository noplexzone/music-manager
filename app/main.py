from __future__ import annotations

import logging
from importlib.resources import files
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.auth import get_current_user, setup_complete
from app.config import get_settings
from app.database import get_db
from app.routers import auth, health, imports, jobs, naming, search, tracks
from app.routers import settings as settings_router

_TEMPLATES_DIR = files("app") / "templates"
_STATIC_DIR = files("app") / "static"

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app = FastAPI(
        title="Music Manager",
        version="0.1.3",
        description="Self-hosted music acquisition and library management",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router, tags=["auth"])
    app.include_router(search.router, tags=["search"])
    app.include_router(settings_router.router, tags=["settings"])
    app.include_router(jobs.router, tags=["jobs", "downloads"])
    app.include_router(tracks.router, tags=["tracks"])
    app.include_router(naming.router, tags=["naming"])
    app.include_router(imports.router, tags=["imports"])

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(
        request: Request,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> Response:
        if not await setup_complete(db):
            return RedirectResponse("/setup", status_code=307)
        try:
            await get_current_user(request, db)
        except HTTPException:
            return RedirectResponse("/login", status_code=307)
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(request, "index.html", {})

    return app


app = create_app()
