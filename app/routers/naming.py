from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.naming.convention import NamingError, render_path
from app.schemas.track import NamingPreviewRequest, NamingPreviewResponse

router = APIRouter()


@router.post("/naming/preview", response_model=NamingPreviewResponse)
async def naming_preview(
    req: NamingPreviewRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> NamingPreviewResponse:
    template = req.template or settings.naming_template
    try:
        rendered = render_path(
            title=req.title,
            artist=req.artist,
            album_artist=req.album_artist,
            album=req.album,
            year=req.year,
            disc=req.disc,
            disc_total=req.disc_total,
            track_no=req.track_no,
            ext=req.ext,
            template=template,
            library_root=settings.library_root,
        )
    except NamingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return NamingPreviewResponse(rendered_path=rendered, template_used=template)
