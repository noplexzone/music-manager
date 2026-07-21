from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.metadata.base import AlbumDetail, AlbumHit, ArtistDetail, ArtistHit, MetadataProvider
from app.metadata.deezer import DeezerClient
from app.metadata.itunes import ITunesClient
from app.metadata.musicbrainz import MusicBrainzClient
from app.models.catalog_entities import CatalogAlbum, CatalogAlbumTrack, CatalogArtist
from app.sources.base import CapabilityState

VALID_METADATA_PROVIDERS = {"musicbrainz", "deezer", "itunes"}


@dataclass(frozen=True)
class ProviderOutcome:
    provider: str
    artists: list[ArtistHit]
    state: CapabilityState


def build_metadata_provider(name: str, settings: Settings) -> MetadataProvider | None:
    if name == "musicbrainz":
        return MusicBrainzClient(settings.musicbrainz_user_agent)
    if name == "deezer":
        return DeezerClient(settings.deezer_api_url)
    if name == "itunes":
        return ITunesClient()
    return None


def provider_ids_for_hit(
    hit: ArtistHit | ArtistDetail | AlbumHit | AlbumDetail,
) -> dict[str, str | None]:
    return {"mbid": hit.mbid, "deezer_id": hit.deezer_id, "itunes_id": hit.itunes_id}


async def search_catalog_artists(
    settings: Settings, query: str, providers: list[str]
) -> list[ProviderOutcome]:
    async def _one(name: str) -> ProviderOutcome:
        provider = build_metadata_provider(name, settings)
        if provider is None:
            return ProviderOutcome(name, [], CapabilityState(False, "Unknown metadata provider"))
        state = await provider.health()
        if not state.available:
            return ProviderOutcome(name, [], state)
        try:
            return ProviderOutcome(
                name, await provider.search_artists(query), CapabilityState(True)
            )
        except Exception as exc:
            return ProviderOutcome(
                name,
                [],
                CapabilityState(
                    False, "Metadata provider search failed", {"error": exc.__class__.__name__}
                ),
            )

    return list(
        await asyncio.gather(*[_one(p) for p in providers if p in VALID_METADATA_PROVIDERS])
    )


async def upsert_catalog_artist(db: AsyncSession, hit: ArtistHit | ArtistDetail) -> CatalogArtist:
    ids = provider_ids_for_hit(hit)
    filters = []
    if ids["mbid"]:
        filters.append(CatalogArtist.mbid == ids["mbid"])
    if ids["deezer_id"]:
        filters.append(CatalogArtist.deezer_id == ids["deezer_id"])
    if ids["itunes_id"]:
        filters.append(CatalogArtist.itunes_id == ids["itunes_id"])
    artist = None
    if filters:
        artist = (await db.scalars(select(CatalogArtist).where(or_(*filters)).limit(1))).first()
    if artist is None:
        artist = CatalogArtist(name=hit.name)
        db.add(artist)
    artist.name = hit.name or artist.name
    artist.artwork_url = hit.artwork_url or artist.artwork_url
    artist.mbid = ids["mbid"] or artist.mbid
    artist.deezer_id = ids["deezer_id"] or artist.deezer_id
    artist.itunes_id = ids["itunes_id"] or artist.itunes_id
    await db.flush()
    return artist


async def open_catalog_artist(
    db: AsyncSession, settings: Settings, provider_name: str, provider_id: str
) -> CatalogArtist:
    provider = build_metadata_provider(provider_name, settings)
    if provider is None:
        raise ValueError("Unknown metadata provider")
    detail = await provider.get_artist(provider_id)
    return await upsert_catalog_artist(db, detail)


def _artist_provider_ref(artist: CatalogArtist) -> tuple[str, str] | None:
    if artist.mbid:
        return "musicbrainz", artist.mbid
    if artist.deezer_id:
        return "deezer", artist.deezer_id
    if artist.itunes_id:
        return "itunes", artist.itunes_id
    return None


def _album_provider_ref(album: CatalogAlbum) -> tuple[str, str] | None:
    if album.mbid:
        return "musicbrainz", album.mbid
    if album.deezer_id:
        return "deezer", album.deezer_id
    if album.itunes_id:
        return "itunes", album.itunes_id
    return None


async def fetch_and_store_discography(
    db: AsyncSession, settings: Settings, artist: CatalogArtist
) -> list[CatalogAlbum]:
    ref = _artist_provider_ref(artist)
    if ref is None:
        return []
    provider_name, provider_id = ref
    provider = build_metadata_provider(provider_name, settings)
    if provider is None:
        return []
    albums = await provider.get_discography(provider_id)
    stored: list[CatalogAlbum] = []
    for hit in albums:
        stored.append(await upsert_catalog_album(db, artist, hit))
    return stored


async def upsert_catalog_album(
    db: AsyncSession, artist: CatalogArtist, hit: AlbumHit | AlbumDetail
) -> CatalogAlbum:
    ids = provider_ids_for_hit(hit)
    filters = []
    if ids["mbid"]:
        filters.append(CatalogAlbum.mbid == ids["mbid"])
    if ids["deezer_id"]:
        filters.append(CatalogAlbum.deezer_id == ids["deezer_id"])
    if ids["itunes_id"]:
        filters.append(CatalogAlbum.itunes_id == ids["itunes_id"])
    album = None
    if filters:
        album = (await db.scalars(select(CatalogAlbum).where(or_(*filters)).limit(1))).first()
    if album is None:
        album = CatalogAlbum(artist_id=artist.id, title=hit.title)
        db.add(album)
    album.artist_id = artist.id
    album.title = hit.title or album.title
    album.year = hit.year or album.year
    album.release_type = hit.release_type or album.release_type
    album.artwork_url = hit.artwork_url or album.artwork_url
    album.track_count = hit.track_count or album.track_count
    album.mbid = ids["mbid"] or album.mbid
    album.deezer_id = ids["deezer_id"] or album.deezer_id
    album.itunes_id = ids["itunes_id"] or album.itunes_id
    await db.flush()
    return album


async def fetch_and_store_album(
    db: AsyncSession, settings: Settings, album: CatalogAlbum
) -> CatalogAlbum:
    ref = _album_provider_ref(album)
    if ref is None:
        return album
    provider_name, provider_id = ref
    provider = build_metadata_provider(provider_name, settings)
    if provider is None:
        return album
    detail = await provider.get_album(provider_id)
    album = await upsert_catalog_album(db, album.artist, detail)
    for existing in list(album.tracks):
        await db.delete(existing)
    await db.flush()
    for track in detail.tracks:
        db.add(
            CatalogAlbumTrack(
                album_id=album.id,
                position=track.position,
                disc=track.disc,
                title=track.title,
                duration_sec=track.duration_sec,
                recording_mbid=track.recording_mbid,
            )
        )
    album.track_count = len(detail.tracks) or album.track_count
    await db.flush()
    await db.refresh(album, ["tracks"])
    return album
