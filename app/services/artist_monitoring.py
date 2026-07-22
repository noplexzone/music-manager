from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models.catalog_entities import CatalogAlbum, CatalogArtist
from app.models.job import Job, JobStatus
from app.services.catalog_metadata import fetch_and_store_discography
from app.settings_service import build_effective_settings, get_runtime_settings


def apply_monitor_policy(artist: CatalogArtist, new_albums: list[CatalogAlbum]) -> None:
    if not artist.monitored:
        return
    for album in new_albums:
        if artist.monitor_policy == "none_new":
            album.monitored = False
        elif artist.monitor_policy == "albums_only":
            album.monitored = (album.release_type or "album").casefold() == "album"
        else:
            album.monitored = True


def wanted_albums(artist: CatalogArtist) -> list[CatalogAlbum]:
    return [a for a in artist.albums if a.monitored and not a.in_library]


async def refresh_monitored_artist(
    db: AsyncSession, settings: Settings, artist: CatalogArtist, *, auto_download: bool = False
) -> list[CatalogAlbum]:
    before = {a.id for a in artist.albums}
    await fetch_and_store_discography(db, settings, artist)
    await db.refresh(artist, ["albums"])
    new = [a for a in artist.albums if a.id not in before]
    apply_monitor_policy(artist, new)
    artist.last_refreshed_at = datetime.now(tz=UTC)
    if auto_download:
        for album in wanted_albums(artist):
            db.add(
                Job(
                    source="priority",
                    query=f"{artist.name} {album.title}",
                    status=JobStatus.pending,
                    catalog_album_id=album.id,
                )
            )
    await db.flush()
    return new


class DiscographyRefreshScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            factory = get_session_factory()
            async with factory() as db:
                cfg = await build_effective_settings(db, get_settings())
                runtime = await get_runtime_settings(db)
                result = await db.execute(
                    select(CatalogArtist)
                    .where(CatalogArtist.monitored.is_(True))
                    .options(selectinload(CatalogArtist.albums))
                )
                for artist in result.scalars():
                    await refresh_monitored_artist(
                        db, cfg, artist, auto_download=runtime.auto_download_wanted
                    )
                await db.commit()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=runtime.discography_refresh_hours * 3600
                )
            except TimeoutError:
                continue
