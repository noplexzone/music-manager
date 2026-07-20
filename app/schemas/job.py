from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.job import JobStatus
from app.schemas.search import SearchResult

JobSource = Literal["slskd", "prowlarr", "youtube"]


class SelectedResultPayload(SearchResult):
    metadata: dict[str, object] = Field(default_factory=dict)


class JobCreate(BaseModel):
    source: JobSource
    query: str
    selected_result: SelectedResultPayload | None = None


class JobRead(BaseModel):
    id: int
    source: str
    query: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    result_json: str | None = None
    selected_result_json: str | None = None
    model_config = {"from_attributes": True}
