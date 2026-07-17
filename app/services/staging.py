from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.naming.convention import _sanitize_segment


class StagingPathError(ValueError):
    pass


def build_staging_release_path(settings: Settings, *, source: str, release_id: int) -> Path:
    safe_source = _sanitize_segment(source)
    if safe_source != source or safe_source in {".", ".."}:
        raise StagingPathError("source cannot escape the staging root")

    root = settings.staging_root.resolve()
    candidate = (root / safe_source / f"release-{release_id}").resolve()
    if root != candidate and root not in candidate.parents:
        raise StagingPathError("staging path escapes the staging root")
    return candidate
