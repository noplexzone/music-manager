from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.track import FingerprintState, IdentityResolutionState


class PathPreviewRead(BaseModel):
    id: int
    track_id: int
    rendered_path: str
    naming_template: str
    computed_at: datetime

    model_config = {"from_attributes": True}


class TrackRead(BaseModel):
    id: int
    job_id: int
    title: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    year: str | None = None
    disc: int | None = None
    disc_total: int | None = None
    track_no: int | None = None
    duration_sec: int | None = None
    mbid: str | None = None
    identity_state: IdentityResolutionState
    acoustid: str | None = None
    deezer_id: str | None = None
    source_path: str | None = None
    source_job_id: str | None = None
    source_status: str | None = None
    source: str
    fingerprint_state: FingerprintState
    path_previews: list[PathPreviewRead] = []

    model_config = {"from_attributes": True}


class NamingPreviewRequest(BaseModel):
    title: str
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    year: str | None = None
    disc: int | None = None
    disc_total: int | None = None
    track_no: int | None = None
    ext: str = "flac"
    template: str | None = None


class NamingPreviewResponse(BaseModel):
    rendered_path: str
    template_used: str
