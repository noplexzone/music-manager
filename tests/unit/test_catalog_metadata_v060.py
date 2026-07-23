from __future__ import annotations

import json

from sqlalchemy import select

from app.config import Settings
from app.metadata.base import AlbumHit, ArtistDetail, ArtistHit
from app.models.catalog_entities import CatalogAlbum, CatalogAlbumTrack, CatalogArtist
from app.models.job import Job, JobStatus
from app.models.track import Track
from app.services import catalog_metadata
from app.services.catalog_metadata import (
    _album_keys_match,
    _norm_title,
    enrich_catalog_artist,
    reconcile_duplicate_catalog_albums,
)


def test_album_title_normalization_folds_typographic_punctuation() -> None:
    assert _norm_title("We Don’t Get Along") == _norm_title("We Don't Get Along")
    mb = AlbumHit(
        provider="musicbrainz",
        provider_id="mb",
        title="We Don’t Get Along",
        year=None,
        release_type="Single",
    )
    dz = AlbumHit(
        provider="deezer",
        provider_id="dz",
        title="We Don't Get Along",
        year="2024",
        release_type="single",
    )
    assert _album_keys_match(mb, dz)


async def test_reconcile_duplicate_catalog_albums_merges_legacy_curly_apostrophe_duplicate(
    db_session,
) -> None:
    artist = CatalogArtist(name="Example")
    db_session.add(artist)
    await db_session.flush()
    loser = CatalogAlbum(
        artist_id=artist.id,
        title="We Don't Get Along",
        year="2024",
        release_type="Single",
        deezer_id="dz1",
        monitored=True,
    )
    winner = CatalogAlbum(
        artist_id=artist.id,
        title="We Don’t Get Along",
        year=None,
        release_type="single",
        mbid="mb1",
        track_count=12,
        artwork_url="cover.jpg",
    )
    db_session.add_all([loser, winner])
    await db_session.flush()
    db_session.add(CatalogAlbumTrack(album_id=loser.id, position=1, disc=1, title="Track"))
    job = Job(
        source="priority",
        query="Example We Don't Get Along",
        status=JobStatus.pending,
        catalog_album_id=loser.id,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(Track(job_id=job.id, source="test", catalog_album_id=loser.id, title="Track"))
    await db_session.flush()

    merged = await reconcile_duplicate_catalog_albums(db_session, artist.id)
    await db_session.commit()

    assert merged == 1
    albums = list((await db_session.scalars(select(CatalogAlbum))).all())
    assert len(albums) == 1
    kept = albums[0]
    assert kept.mbid == "mb1"
    assert kept.deezer_id == "dz1"
    assert kept.monitored is True
    assert (await db_session.scalars(select(CatalogAlbumTrack.album_id))).one() == kept.id
    assert (await db_session.scalars(select(Job.catalog_album_id))).one() == kept.id
    assert (await db_session.scalars(select(Track.catalog_album_id))).one() == kept.id
    assert await reconcile_duplicate_catalog_albums(db_session, artist.id) == 0


class FakeMusicBrainzProvider:
    async def search_artists(self, query: str) -> list[ArtistHit]:
        return [
            ArtistHit(
                provider="musicbrainz", provider_id="artist-mbid", name=query, mbid="artist-mbid"
            )
        ]

    async def get_artist(self, id: str) -> ArtistDetail:
        return ArtistDetail(provider="musicbrainz", provider_id=id, name="Known Artist", mbid=id)

    async def get_discography(self, id: str) -> list[AlbumHit]:
        return [
            AlbumHit(
                provider="musicbrainz",
                provider_id="mb-album",
                title="Known Album",
                year="2024",
                release_type="Album",
                mbid="mb-album",
            )
        ]


async def test_enrichment_resolves_mbid_from_conservative_discography_overlap(
    db_session, monkeypatch, test_settings: Settings
) -> None:
    artist = CatalogArtist(name="Known Artist", deezer_id="123")
    db_session.add(artist)
    await db_session.flush()
    db_session.add(
        CatalogAlbum(
            artist_id=artist.id,
            title="Known Album",
            year="2024",
            release_type="Album",
            deezer_id="dz-album",
        )
    )
    await db_session.flush()
    await db_session.refresh(artist, ["albums"])

    monkeypatch.setattr(
        catalog_metadata,
        "build_metadata_provider",
        lambda name, settings: FakeMusicBrainzProvider() if name == "musicbrainz" else None,
    )

    outcome = await enrich_catalog_artist(db_session, test_settings, artist, ["musicbrainz"])
    assert outcome["status"] == "ok"
    assert artist.mbid == "artist-mbid"
    assert json.loads(artist.provenance_json or "{}")["mbid"] == "musicbrainz"
