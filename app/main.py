from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.routers import health, imports, jobs, naming, search, tracks

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app = FastAPI(
        title="Music Manager",
        version="0.1.1",
        description="Self-hosted music acquisition and library management",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(health.router, tags=["health"])
    app.include_router(search.router, tags=["search"])
    app.include_router(jobs.router, tags=["jobs"])
    app.include_router(tracks.router, tags=["tracks"])
    app.include_router(naming.router, tags=["naming"])
    app.include_router(imports.router, tags=["imports"])

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request) -> HTMLResponse:
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(request, "index.html", {})

    return app


app = create_app()
