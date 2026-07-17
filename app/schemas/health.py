from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceStatus(BaseModel):
    available: bool
    reason: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    sources: dict[str, SourceStatus]
    db_writable: bool = True
