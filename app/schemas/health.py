from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SourceStatus(BaseModel):
    available: bool
    reason: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    sources: dict[str, SourceStatus]
    db_writable: bool = True
