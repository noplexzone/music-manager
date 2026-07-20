from __future__ import annotations

import asyncio
import logging
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models.track import Track
from app.settings_service import build_effective_settings

logger = logging.getLogger(__name__)
_BATCH_SIZE = 200
_MAX_ROWS_PER_RUN = 10_000
_RETRY_INTERVAL = timedelta(hours=24)


@dataclass(frozen=True)
class FileMetadata:
    fmt: str
    size_bytes: int


def _open_metadata_under_root(path: Path, root: Path) -> FileMetadata | None:
    if not path.is_absolute() or not root.is_absolute():
        return None
    normalized_path = Path(os.path.normpath(path))
    normalized_root = Path(os.path.normpath(root))
    try:
        relative = normalized_path.relative_to(normalized_root)
    except ValueError:
        return None
    if not relative.parts:
        return None

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(normalized_root, directory_flags)
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fd)
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            return None
        suffix = normalized_path.suffix.casefold().lstrip(".")
        if not suffix or len(suffix) > 16 or not suffix.isalnum():
            return None
        return FileMetadata(fmt=suffix, size_bytes=file_stat.st_size)
    except OSError:
        return None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def read_safe_file_metadata(raw_path: str, roots: tuple[Path, ...]) -> FileMetadata | None:
    if not raw_path or "://" in raw_path:
        return None
    path = Path(raw_path)
    for root in roots:
        if metadata := _open_metadata_under_root(path, root):
            return metadata
    return None


async def reconcile_track_file_metadata(
    db: AsyncSession,
    settings: Settings,
    *,
    batch_size: int = _BATCH_SIZE,
    max_rows: int = _MAX_ROWS_PER_RUN,
) -> int:
    batch_size = max(1, min(batch_size, _BATCH_SIZE))
    max_rows = max(0, min(max_rows, _MAX_ROWS_PER_RUN))
    roots = (settings.library_root.absolute(), settings.staging_root.absolute())
    scan_started_at = datetime.now(UTC)
    retry_before = scan_started_at - _RETRY_INTERVAL
    examined = 0
    updated = 0

    while examined < max_rows:
        limit = min(batch_size, max_rows - examined)
        unchecked_first = case((Track.file_metadata_checked_at.is_(None), 0), else_=1)
        stmt = (
            select(Track)
            .where(
                or_(Track.file_format.is_(None), Track.file_size_bytes.is_(None)),
                or_(
                    Track.file_metadata_checked_at.is_(None),
                    Track.file_metadata_checked_at <= retry_before,
                ),
            )
            .order_by(unchecked_first, Track.file_metadata_checked_at, Track.id)
            .limit(limit)
        )
        tracks = list((await db.scalars(stmt)).all())
        if not tracks:
            break
        for track in tracks:
            examined += 1
            track.file_metadata_checked_at = scan_started_at
            raw_path = track.source_path or track.staging_path or ""
            metadata = await asyncio.to_thread(read_safe_file_metadata, raw_path, roots)
            if metadata is None:
                continue
            changed = False
            if track.file_format is None:
                track.file_format = metadata.fmt
                changed = True
            if track.file_size_bytes is None:
                track.file_size_bytes = metadata.size_bytes
                changed = True
            if changed:
                updated += 1
        # Commit each bounded batch so scan progress survives a later crash or timeout.
        await db.commit()
    return updated


async def _main() -> None:
    factory = get_session_factory()
    async with factory() as db:
        settings = await build_effective_settings(db, get_settings())
        updated = await reconcile_track_file_metadata(db, settings)
        await db.commit()
    logger.info("Reconciled file metadata for %d track(s)", updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
