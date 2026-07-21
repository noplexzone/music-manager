from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.crypto import decrypt_secret, encrypt_secret
from app.database import get_db
from app.models.settings import AppSetting, ProviderSetting

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime settings (source priority, result cap) — stored in app_settings
# ---------------------------------------------------------------------------

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


async def _load_runtime(db: AsyncSession) -> dict[str, str]:
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
    values = await _load_runtime(db)
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


# ---------------------------------------------------------------------------
# Provider settings (encrypted secrets, path overrides) — stored in provider_settings
# ---------------------------------------------------------------------------

# Keys that map directly to Settings attributes (env vars are authoritative when non-blank).
_ENV_BACKED_KEYS: dict[str, str] = {
    "slskd_url": "slskd_url",
    "slskd_api_key": "slskd_api_key",
    "prowlarr_url": "prowlarr_url",
    "prowlarr_api_key": "prowlarr_api_key",
    "sabnzbd_url": "sabnzbd_url",
    "sabnzbd_api_key": "sabnzbd_api_key",
    "ytdlp_cookies_file": "ytdlp_cookies_file",
    "musicbrainz_contact": "musicbrainz_contact",
    "acoustid_api_key": "acoustid_api_key",
    "library_root": "library_root",
    "staging_root": "staging_root",
    "naming_template": "naming_template",
    "tidal_config_path": "tidal_config_path",
    "tidal_session_path": "tidal_session_path",
    "tidal_quality": "tidal_quality",
}

# Keys with no corresponding env var — stored in DB only.
DB_ONLY_KEYS: frozenset[str] = frozenset()

ALL_KEYS: tuple[str, ...] = tuple(_ENV_BACKED_KEYS) + tuple(sorted(DB_ONLY_KEYS))

# Settings keys whose values must be encrypted at rest.
SECRET_KEYS: frozenset[str] = frozenset(
    {"slskd_api_key", "prowlarr_api_key", "sabnzbd_api_key", "acoustid_api_key"}
)

# Settings keys that store Path objects in Settings (need str↔Path conversion).
_PATH_KEYS: frozenset[str] = frozenset({"library_root", "staging_root"})


@dataclass
class EffectiveValue:
    value: str  # masked ("***") for secrets; raw for plain fields
    configured: bool
    locked_by_environment: bool


def _get_env_raw(settings: Settings, attr: str) -> str:
    """Return the explicitly-set env/config value for *attr*, or '' for model defaults."""
    if attr not in settings.model_fields_set:
        return ""
    val = getattr(settings, attr, "")
    if isinstance(val, Path):
        return str(val)
    return str(val) if val is not None else ""


async def load_raw_db_values(db: AsyncSession, secret_key: str) -> dict[str, str]:
    """Fetch all stored provider settings with secrets decrypted."""
    rows = (await db.scalars(select(ProviderSetting))).all()
    result: dict[str, str] = {}
    for row in rows:
        if row.value_encrypted is not None:
            try:
                result[row.key] = decrypt_secret(row.value_encrypted, secret_key)
            except Exception:
                logger.warning("Failed to decrypt provider setting %r — skipping", row.key)
        elif row.value_plain is not None:
            result[row.key] = row.value_plain
    return result


def compute_effective_value(
    key: str,
    env_settings: Settings,
    db_values: dict[str, str],
) -> EffectiveValue:
    is_db_only = key in DB_ONLY_KEYS
    is_secret = key in SECRET_KEYS

    env_raw = "" if is_db_only else _get_env_raw(env_settings, _ENV_BACKED_KEYS.get(key, key))
    locked = bool(env_raw)

    raw = env_raw if locked else db_values.get(key, "")
    configured = bool(raw)
    display = "***" if configured and is_secret else raw

    return EffectiveValue(
        value=display,
        configured=configured,
        locked_by_environment=locked,
    )


async def get_all_effective(db: AsyncSession, env_settings: Settings) -> dict[str, EffectiveValue]:
    db_values = await load_raw_db_values(db, env_settings.secret_key)
    return {k: compute_effective_value(k, env_settings, db_values) for k in ALL_KEYS}


async def save_settings(
    db: AsyncSession,
    updates: dict[str, str],
    env_settings: Settings,
    *,
    validate_only: bool = False,
) -> None:
    """Persist *updates* to provider_settings in the DB."""
    if validate_only:
        return

    for key, new_val in updates.items():
        if key not in set(ALL_KEYS):
            continue

        is_db_only = key in DB_ONLY_KEYS
        is_secret = key in SECRET_KEYS

        if not is_db_only:
            env_raw = _get_env_raw(env_settings, _ENV_BACKED_KEYS.get(key, key))
            if env_raw:
                continue

        if is_secret and not new_val:
            continue

        row = await db.get(ProviderSetting, key)

        if not new_val:
            if row is not None:
                await db.delete(row)
            continue

        if row is None:
            row = ProviderSetting(key=key)
            db.add(row)

        if is_secret:
            row.value_encrypted = encrypt_secret(new_val, env_settings.secret_key)
            row.value_plain = None
        else:
            row.value_plain = new_val
            row.value_encrypted = None

        row.updated_at = datetime.now(UTC)


def resolve_for_probe(key: str, supplied: str, env: Settings, raw_db: dict[str, str]) -> str:
    """Return the value to use when probing *key*: supplied → env → DB."""
    if supplied:
        return supplied
    env_raw = _get_env_raw(env, _ENV_BACKED_KEYS.get(key, key))
    return env_raw if env_raw else raw_db.get(key, "")


async def build_effective_settings(db: AsyncSession, env: Settings) -> Settings:
    """Return a Settings copy with DB overrides applied for non-locked fields."""
    db_values = await load_raw_db_values(db, env.secret_key)
    overrides: dict[str, object] = {}
    for key, attr in _ENV_BACKED_KEYS.items():
        env_raw = _get_env_raw(env, attr)
        if env_raw:
            continue
        db_val = db_values.get(key, "")
        if not db_val:
            continue
        if key in _PATH_KEYS:
            overrides[attr] = Path(db_val)
        else:
            overrides[attr] = db_val
    if not overrides:
        return env
    return env.model_copy(update=overrides)


async def effective_settings_dep(
    db: Annotated[AsyncSession, Depends(get_db)],
    env: Annotated[Settings, Depends(get_settings)],
) -> Settings:
    """FastAPI dependency — returns env Settings merged with DB overrides."""
    return await build_effective_settings(db, env)
