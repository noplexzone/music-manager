from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.job import Job, JobStatus
from app.models.track import FingerprintState, IdentityResolutionState, Track
from app.models.workflow import AcquisitionState, ImportWorkflowState
from app.services import catalog_reconcile
from app.services.catalog_reconcile import FileMetadata, reconcile_track_file_metadata


def _track(job_id: int, path: str) -> Track:
    return Track(
        job_id=job_id,
        source="slskd",
        source_path=path,
        acquisition_state=AcquisitionState.downloaded,
        import_state=ImportWorkflowState.imported,
        fingerprint_state=FingerprintState.pending,
        identity_state=IdentityResolutionState.pending,
    )


async def test_reconcile_backfills_only_regular_files_under_managed_roots(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    library = tmp_path / "library"
    staging = tmp_path / "staging"
    library.mkdir()
    staging.mkdir()
    audio = library / "artist" / "track.FLAC"
    audio.parent.mkdir()
    audio.write_bytes(b"audio-bytes")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"outside")
    symlink = library / "linked.mp3"
    symlink.symlink_to(outside)

    job = Job(source="slskd", query="reconcile", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    managed = _track(job.id, str(audio))
    external = _track(job.id, str(outside))
    linked = _track(job.id, str(symlink))
    remote = _track(job.id, "https://example.invalid/track.mp3")
    db_session.add_all([managed, external, linked, remote])
    await db_session.flush()

    settings = Settings(
        secret_key="test-secret",
        library_root=library,
        staging_root=staging,
        _env_file=None,
    )
    updated = await reconcile_track_file_metadata(db_session, settings)

    assert updated == 1
    assert managed.file_format == "flac"
    assert managed.file_size_bytes == len(b"audio-bytes")
    assert external.file_format is None and external.file_size_bytes is None
    assert linked.file_format is None and linked.file_size_bytes is None
    assert remote.file_format is None and remote.file_size_bytes is None


async def test_reconcile_is_bounded_and_preserves_existing_values(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    library = tmp_path / "library"
    staging = tmp_path / "staging"
    library.mkdir()
    staging.mkdir()
    job = Job(source="slskd", query="bounded", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    tracks: list[Track] = []
    for index in range(3):
        audio = library / f"{index}.mp3"
        audio.write_bytes(b"1234")
        track = _track(job.id, str(audio))
        tracks.append(track)
    tracks[0].file_format = "custom"
    db_session.add_all(tracks)
    await db_session.flush()

    settings = Settings(
        secret_key="test-secret",
        library_root=library,
        staging_root=staging,
        _env_file=None,
    )
    updated = await reconcile_track_file_metadata(db_session, settings, batch_size=1, max_rows=1)

    assert updated == 1
    assert tracks[0].file_format == "custom"
    assert tracks[0].file_size_bytes == 4
    assert tracks[1].file_size_bytes is None


async def test_reconcile_progresses_past_unreconcilable_rows(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    library = tmp_path / "library"
    staging = tmp_path / "staging"
    library.mkdir()
    staging.mkdir()
    audio = library / "valid.flac"
    audio.write_bytes(b"valid")
    job = Job(source="slskd", query="progress", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    invalid = _track(job.id, "https://example.invalid/first.mp3")
    valid = _track(job.id, str(audio))
    db_session.add_all([invalid, valid])
    await db_session.flush()
    settings = Settings(
        secret_key="test-secret",
        library_root=library,
        staging_root=staging,
        _env_file=None,
    )

    assert await reconcile_track_file_metadata(db_session, settings, max_rows=1) == 0
    assert invalid.file_metadata_checked_at is not None
    assert valid.file_size_bytes is None
    assert await reconcile_track_file_metadata(db_session, settings, max_rows=1) == 1
    assert valid.file_format == "flac"
    assert valid.file_size_bytes == 5


async def test_reconcile_commits_progress_before_later_batch_failure(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    staging = tmp_path / "staging"
    library.mkdir()
    staging.mkdir()
    valid_audio = library / "valid.mp3"
    valid_audio.write_bytes(b"valid")
    job = Job(source="slskd", query="checkpoint", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    first = _track(job.id, "https://example.invalid/first.mp3")
    second = _track(job.id, str(valid_audio))
    db_session.add_all([first, second])
    await db_session.commit()
    first_id, second_id = first.id, second.id
    settings = Settings(
        secret_key="test-secret",
        library_root=library,
        staging_root=staging,
        _env_file=None,
    )

    calls = 0

    def fail_on_second_path(raw_path: str, roots: tuple[Path, ...]) -> FileMetadata | None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated second-batch failure")
        return None

    monkeypatch.setattr(catalog_reconcile, "read_safe_file_metadata", fail_on_second_path)
    assert db_session.bind is not None
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as failed_run:
        with pytest.raises(RuntimeError, match="second-batch"):
            await reconcile_track_file_metadata(failed_run, settings, batch_size=1, max_rows=2)
        await failed_run.rollback()

    monkeypatch.undo()
    async with factory() as next_run:
        persisted_first = await next_run.get(Track, first_id)
        persisted_second = await next_run.get(Track, second_id)
        assert persisted_first is not None
        assert persisted_second is not None
        assert persisted_first.file_metadata_checked_at is not None
        assert persisted_second.file_metadata_checked_at is None
        assert (
            await reconcile_track_file_metadata(next_run, settings, batch_size=1, max_rows=1) == 1
        )
        assert persisted_second.file_format == "mp3"
        assert persisted_second.file_size_bytes == 5
