from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.track import Track


class CatalogArtist(Base):
    __tablename__ = "catalog_artists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mbid: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    deezer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    itunes_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    artwork_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    albums: Mapped[list[CatalogAlbum]] = relationship(
        "CatalogAlbum", back_populates="artist", cascade="all, delete-orphan"
    )


class CatalogAlbum(Base):
    __tablename__ = "catalog_albums"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_artists.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[str | None] = mapped_column(String(4), nullable=True)
    release_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mbid: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    deezer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    itunes_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    artwork_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    artist: Mapped[CatalogArtist] = relationship("CatalogArtist", back_populates="albums")
    tracks: Mapped[list[CatalogAlbumTrack]] = relationship(
        "CatalogAlbumTrack",
        back_populates="album",
        cascade="all, delete-orphan",
        order_by="CatalogAlbumTrack.disc, CatalogAlbumTrack.position",
    )
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="catalog_album")
    library_tracks: Mapped[list[Track]] = relationship("Track", back_populates="catalog_album")


class CatalogAlbumTrack(Base):
    __tablename__ = "catalog_album_tracks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    album_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_albums.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    disc: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_mbid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    album: Mapped[CatalogAlbum] = relationship("CatalogAlbum", back_populates="tracks")
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="catalog_track")
    library_tracks: Mapped[list[Track]] = relationship("Track", back_populates="catalog_track")
