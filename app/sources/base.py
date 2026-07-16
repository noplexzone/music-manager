from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.schemas.search import SearchRequest, SearchResult


@dataclass
class CapabilityState:
    available: bool
    reason: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    name: str

    async def health(self) -> CapabilityState: ...

    async def search(self, query: SearchRequest) -> list[SearchResult]: ...
