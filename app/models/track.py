from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.path_preview import PathPreview


class FingerprintState(StrEnum):
    pending = "pending"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class IdentityResolutionState(StrEnum):
    pending = "pending"
    resolved = "resolved"
    unresolved = "unresolved"


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    artist: Mapped[str | None] = mapped_column(Text, nullable=True)
    album_artist: Mapped[str | None] = mapped_column(Text, nullable=True)
    album: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[str | None] = mapped_column(String(4), nullable=True)
    disc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mbid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    identity_state: Mapped[IdentityResolutionState] = mapped_column(
        Enum(IdentityResolutionState),
        nullable=False,
        default=IdentityResolutionState.pending,
    )
    acoustid: Mapped[str | None] = mapped_column(Text, nullable=True)
    deezer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_state: Mapped[FingerprintState] = mapped_column(
        Enum(FingerprintState),
        nullable=False,
        default=FingerprintState.pending,
    )

    job: Mapped[Job] = relationship("Job", back_populates="tracks")
    path_previews: Mapped[list[PathPreview]] = relationship(
        "PathPreview", back_populates="track", cascade="all, delete-orphan"
    )
