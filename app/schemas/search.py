from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.health import SourceStatus


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    sources: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    source: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration_sec: int | None = None
    size_bytes: int | None = None
    format: str | None = None
    url: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[SearchResult]
    source_states: dict[str, SourceStatus]
