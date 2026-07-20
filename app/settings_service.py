from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting

DEFAULT_SOURCE_PRIORITY: list[dict[str, object]] = [
    {"name": "slskd", "enabled": True},
    {"name": "prowlarr", "enabled": True},
    {"name": "youtube", "enabled": True},
    {"name": "tidal", "enabled": False},
]
VALID_SOURCES = {str(item["name"]) for item in DEFAULT_SOURCE_PRIORITY}
DEFAULT_FREE_TEXT_RESULT_LIMIT = 10
_cache: dict[str, str] | None = None


@dataclass(frozen=True)
class RuntimeSettings:
    source_priority: list[dict[str, object]]
    free_text_result_limit: int

    @property
    def enabled_sources(self) -> list[str]:
        return [str(item["name"]) for item in self.source_priority if item.get("enabled") is True]


async def _load(db: AsyncSession) -> dict[str, str]:
    global _cache
    if _cache is None:
        result = await db.execute(select(AppSetting))
        _cache = {row.key: row.value for row in result.scalars()}
    return dict(_cache)


def _normalize_priority(raw: object) -> list[dict[str, object]]:
    enabled_by_name = {
        str(item["name"]): bool(item.get("enabled", True)) for item in DEFAULT_SOURCE_PRIORITY
    }
    order: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                name, enabled = item, True
            elif isinstance(item, dict):
                name, enabled = str(item.get("name", "")), bool(item.get("enabled", True))
            else:
                continue
            if name in VALID_SOURCES and name not in order:
                order.append(name)
                enabled_by_name[name] = enabled
    for item in DEFAULT_SOURCE_PRIORITY:
        name = str(item["name"])
        if name not in order:
            order.append(name)
    return [{"name": name, "enabled": enabled_by_name[name]} for name in order]


async def get_runtime_settings(db: AsyncSession) -> RuntimeSettings:
    values = await _load(db)
    try:
        priority_raw = json.loads(values.get("source_priority", "[]"))
    except json.JSONDecodeError:
        priority_raw = []
    try:
        limit = int(values.get("free_text_result_limit", str(DEFAULT_FREE_TEXT_RESULT_LIMIT)))
    except ValueError:
        limit = DEFAULT_FREE_TEXT_RESULT_LIMIT
    return RuntimeSettings(_normalize_priority(priority_raw), max(1, min(limit, 100)))


async def save_runtime_settings(
    db: AsyncSession, source_priority: list[dict[str, object]], free_text_result_limit: int
) -> None:
    global _cache
    normalized = _normalize_priority(source_priority)
    payloads = {
        "source_priority": json.dumps(normalized),
        "free_text_result_limit": str(max(1, min(free_text_result_limit, 100))),
    }
    for key, value in payloads.items():
        setting = await db.get(AppSetting, key)
        if setting is None:
            db.add(AppSetting(key=key, value=value))
        else:
            setting.value = value
    await db.flush()
    _cache = None
