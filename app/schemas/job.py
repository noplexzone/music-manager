from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.job import JobStatus


class JobCreate(BaseModel):
    source: str
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
