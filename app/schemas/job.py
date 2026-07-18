from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.job import JobStatus

JobSource = Literal["slskd", "prowlarr", "youtube", "tidal"]


class JobCreate(BaseModel):
    source: JobSource
    query: str


class JobRead(BaseModel):
    id: int
    source: str
    query: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    result_json: str | None = None

    model_config = {"from_attributes": True}
