from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_plan import CollisionState, TagVerificationState
from app.models.job import Job, JobStatus
from app.models.release import Release
from app.models.track import Track
from app.models.workflow import ImportWorkflowState
from app.services.library_import import (
    ImportExecutionError,
    MutagenTagWriter,
    execute_release_import,
    plan_release_import,
)


async def _release_with_staged_tracks(
    db_session: AsyncSession, tmp_path: Path, count: int = 1
) -> tuple[Release, list[Track]]:
    staging = tmp_path / "staging"
    staging.mkdir()
    job = Job(source="slskd", query="artist album", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    release = Release(
        job_id=job.id,
        source="slskd",
        title="Album",
        album_artist="Artist",
        year="1999",
        release_mbid="release-mbid",
        track_count=count,
        staging_path=str(staging),
        import_state=ImportWorkflowState.ready,
    )
    db_session.add(release)
    await db_session.flush()
    tracks: list[Track] = []
    for index in range(1, count + 1):
        source = staging / f"{index:02d}.mp3"
        source.write_bytes(f"audio-{index}".encode())
        track = Track(
            job_id=job.id,
            release_id=release.id,
            title=f"Song {index}",
            artist="Artist",
            album_artist="Artist",
            album="Album",
            year="1999",
            disc=1,
            disc_total=1,
            track_no=index,
            mbid=f"recording-{index}",
            source="slskd",
            staging_path=str(source),
            source_path=str(source),
            import_state=ImportWorkflowState.ready,
        )
        db_session.add(track)
        tracks.append(track)
    await db_session.flush()
    return release, tracks


async def test_plan_detects_same_path_conflict_and_same_bytes_duplicate(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    release, tracks = await _release_with_staged_tracks(db_session, tmp_path, count=1)
    library = tmp_path / "library"
    destination = library / "Artist" / "1999 - Album" / "01 - Song 1.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"different")

    plans = await plan_release_import(db_session, release, library_root=library)
    assert plans[0].collision_state == CollisionState.conflict
    assert plans[0].status == ImportWorkflowState.needs_review
    assert "different bytes" in (plans[0].error_detail or "")

    destination.write_bytes((Path(tracks[0].staging_path or "")).read_bytes())  # noqa: ASYNC240
    plans = await plan_release_import(db_session, release, library_root=library)
    assert plans[0].collision_state == CollisionState.duplicate
    assert plans[0].status == ImportWorkflowState.needs_review
    assert "same bytes" in (plans[0].error_detail or "")


async def test_plan_rejects_symlink_destination_parent(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    release, _tracks = await _release_with_staged_tracks(db_session, tmp_path, count=1)
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (library / "Artist").symlink_to(outside, target_is_directory=True)

    plans = await plan_release_import(db_session, release, library_root=library)

    assert plans[0].collision_state == CollisionState.needs_review
    assert plans[0].status == ImportWorkflowState.needs_review
    assert "symlink" in (plans[0].error_detail or "")


async def test_execute_import_copies_to_destination_temp_writes_verified_tags_and_retains_source(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    release, tracks = await _release_with_staged_tracks(db_session, tmp_path, count=1)
    library = tmp_path / "library"
    plans = await plan_release_import(db_session, release, library_root=library)
    source = Path(tracks[0].staging_path or "")

    imported = await execute_release_import(
        db_session, release, library_root=library, tag_writer=MutagenTagWriter()
    )

    destination = Path(imported[0].destination_path)
    assert destination.exists()  # noqa: ASYNC240
    assert source.exists()  # noqa: ASYNC240
    assert imported[0].destination_temp_path is not None
    assert str(destination.parent) in imported[0].destination_temp_path
    assert imported[0].tag_verification_state == TagVerificationState.verified
    assert imported[0].status == ImportWorkflowState.imported
    assert release.import_state == ImportWorkflowState.imported
    readback = MutagenTagWriter().read_tags(destination)
    assert readback["title"] == "Song 1"
    assert readback["musicbrainz_trackid"] == "recording-1"
    assert plans[0].planned_operations_json is not None


async def test_execute_import_rechecks_destination_race_and_rolls_back(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    release, _tracks = await _release_with_staged_tracks(db_session, tmp_path, count=1)
    library = tmp_path / "library"
    await plan_release_import(db_session, release, library_root=library)

    def race(destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"racer")

    with pytest.raises(ImportExecutionError, match="destination appeared"):
        await execute_release_import(
            db_session,
            release,
            library_root=library,
            tag_writer=MutagenTagWriter(),
            before_commit=race,
        )

    assert release.import_state == ImportWorkflowState.rolled_back
    assert list(library.rglob("*.tmp")) == []


class FailingSecondTagWriter(MutagenTagWriter):
    def __init__(self) -> None:
        self.calls = 0

    def write_and_verify(self, path: Path, tags: dict[str, str]) -> bool:
        self.calls += 1
        return self.calls == 1 and super().write_and_verify(path, tags)


async def test_rollback_removes_prior_imported_tracks_after_later_tag_failure(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    release, tracks = await _release_with_staged_tracks(db_session, tmp_path, count=2)
    library = tmp_path / "library"
    await plan_release_import(db_session, release, library_root=library)

    with pytest.raises(ImportExecutionError, match="tag readback failed"):
        await execute_release_import(
            db_session, release, library_root=library, tag_writer=FailingSecondTagWriter()
        )

    assert release.import_state == ImportWorkflowState.rolled_back
    assert not list(library.rglob("*.mp3"))
    assert Path(tracks[0].staging_path or "").exists()  # noqa: ASYNC240
    assert Path(tracks[1].staging_path or "").exists()  # noqa: ASYNC240
