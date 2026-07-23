from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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
        started = time.perf_counter()
        provider = build_metadata_provider(name, settings)
        if provider is None:
            return ProviderOutcome(name, [], CapabilityState(False, "Unknown metadata provider"))
        state = await provider.health()
        if not state.available:
            return ProviderOutcome(name, [], state)
        try:
            artists = await provider.search_artists(query)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return ProviderOutcome(
                name, artists, CapabilityState(True, extra={"elapsed_ms": elapsed_ms})
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


def _norm_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _edition_marker(value: str) -> str:
    lowered = value.casefold()
    markers = [m for m in ["deluxe", "remaster", "anniversary", "expanded"] if m in lowered]
    return ":".join(markers)


def _album_key(hit: Any) -> tuple[str, str | None, str]:
    return (_norm_title(str(hit.title)), hit.year, _edition_marker(str(hit.title)))


def _name_similarity(a: str, b: str) -> float:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    aw, bw = set(na.split()), set(nb.split())
    return len(aw & bw) / max(len(aw | bw), 1)


async def enrich_catalog_artist(
    db: AsyncSession,
    settings: Settings,
    artist: CatalogArtist,
    enabled_providers: list[str],
    *,
    choices: dict[str, str] | None = None,
) -> dict[str, object]:
    """Best-effort conservative cross-provider enrichment.

    Returns {status: ok|ambiguous, candidates?: [...]} and never clobbers an existing mbid.
    """
    choices = choices or {}
    known_provider = _artist_provider_ref(artist)
    skip = {known_provider[0]} if known_provider else set()
    provenance: dict[str, object] = (
        json.loads(artist.provenance_json or "{}") if artist.provenance_json else {}
    )
    existing_albums = list(artist.albums)
    existing_keys = {_album_key(a) for a in existing_albums}
    ambiguous: list[dict[str, object]] = []
    for provider_name in [
        p for p in enabled_providers if p in VALID_METADATA_PROVIDERS and p not in skip
    ]:
        provider = build_metadata_provider(provider_name, settings)
        if provider is None:
            continue
        hits = await provider.search_artists(artist.name)
        scored: list[tuple[float, ArtistHit]] = []
        for hit in hits[:5]:
            score = _name_similarity(artist.name, hit.name)
            try:
                detail = await provider.get_artist(hit.provider_id)
                albums = await provider.get_discography(hit.provider_id)
                overlap = len({_album_key(a) for a in albums} & existing_keys)
                score += min(overlap / max(len(existing_keys), 1), 1.0)
            except Exception:
                detail = None
            scored.append((score, hit))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored or scored[0][0] < 0.82:
            continue
        if (
            len(scored) > 1
            and scored[0][0] - scored[1][0] < 0.15
            and choices.get(provider_name) != scored[0][1].provider_id
        ):
            ambiguous.append(
                {"provider": provider_name, "candidates": [h.__dict__ for _, h in scored[:3]]}
            )
            continue
        chosen = choices.get(provider_name, scored[0][1].provider_id)
        detail = await provider.get_artist(chosen)
        ids = provider_ids_for_hit(detail)
        if not artist.mbid and ids.get("mbid"):
            artist.mbid = ids["mbid"]
            provenance["mbid"] = provider_name
        if not artist.deezer_id and ids.get("deezer_id"):
            artist.deezer_id = ids["deezer_id"]
            provenance["deezer_id"] = provider_name
        if not artist.itunes_id and ids.get("itunes_id"):
            artist.itunes_id = ids["itunes_id"]
            provenance["itunes_id"] = provider_name
        if detail.artwork_url and (
            not artist.artwork_url or len(detail.artwork_url) > len(artist.artwork_url)
        ):
            artist.artwork_url = detail.artwork_url
            provenance["artwork_url"] = provider_name
        for album_hit in await provider.get_discography(chosen):
            key = _album_key(album_hit)
            album = next((a for a in artist.albums if _album_key(a) == key), None)
            if album is None:
                album = await upsert_catalog_album(db, artist, album_hit)
            providers = (
                set(json.loads(album.providers_json or "[]")) if album.providers_json else set()
            )
            providers.add(provider_name)
            album.providers_json = json.dumps(sorted(providers))
    artist.provenance_json = json.dumps(provenance, sort_keys=True)
    artist.last_enriched_at = datetime.now(tz=UTC)
    await db.flush()
    if ambiguous:
        return {"status": "ambiguous", "candidates": ambiguous}
    return {"status": "ok"}
