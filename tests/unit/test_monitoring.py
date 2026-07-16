from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.models.import_plan import CollisionState
from app.models.job import Job, JobStatus
from app.models.monitoring import MonitoringRecord, MonitoringStatus
from app.models.release import Release
from app.models.release_candidate import ReleaseCandidate
from app.models.track import Track
from app.models.workflow import ImportWorkflowState
from app.services.monitoring import (
    MonitoringCheckAlreadyRunning,
    QualityProfile,
    evaluate_quality_candidate,
    run_monitoring_check,
)


def test_quality_candidate_requires_confident_meaningful_gain() -> None:
    profile = QualityProfile(preferred_codecs=("flac", "mp3"), minimum_bitrate_kbps=320)
    current = {"codec": "mp3", "bitrate_kbps": 320, "reliability": 0.9}
    assert evaluate_quality_candidate(
        profile, current, {"codec": "flac", "lossless": True, "reliability": 0.9}, 0.95
    ).meaningful
    assert not evaluate_quality_candidate(
        profile, current, {"codec": "mp3", "bitrate_kbps": 321, "reliability": 0.9}, 0.95
    ).meaningful
    assert not evaluate_quality_candidate(
        profile, current, {"codec": "flac", "lossless": True, "reliability": 0.9}, 0.70
    ).meaningful


async def test_monitoring_check_is_non_overlapping_and_persists_history(db_session) -> None:
    job = Job(source="slskd", query="album", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    release = Release(job_id=job.id, source="slskd", title="Album")
    db_session.add(release)
    await db_session.flush()
    record = MonitoringRecord(
        release_id=release.id,
        desired_quality_json=QualityProfile(preferred_codecs=("flac",)).to_json(),
    )
    db_session.add(record)
    await db_session.flush()
    entered = asyncio.Event()
    resume = asyncio.Event()

    async def discover() -> list[ReleaseCandidate]:
        entered.set()
        await resume.wait()
        return []

    first = asyncio.create_task(run_monitoring_check(db_session, record, {}, discover))
    await entered.wait()
    with pytest.raises(MonitoringCheckAlreadyRunning):
        await run_monitoring_check(db_session, record, {}, discover)
    resume.set()
    await first
    assert record.status == MonitoringStatus.active
    assert json.loads(record.history_json or "[]")[-1]["outcome"] == "no_upgrade"
    assert record.last_checked_at is not None


async def test_upgrade_failure_preserves_existing_library_file(db_session, tmp_path: Path) -> None:
    from app.services.library_import import (
        ImportExecutionError,
        execute_release_import,
        plan_release_import,
    )

    job = Job(source="slskd", query="album", status=JobStatus.done)
    db_session.add(job)
    await db_session.flush()
    release = Release(
        job_id=job.id,
        source="slskd",
        title="Album",
        album_artist="Artist",
        year="2000",
        import_state=ImportWorkflowState.ready,
    )
    db_session.add(release)
    await db_session.flush()
    staged = tmp_path / "candidate.wav"
    staged.write_bytes(b"new candidate")
    track = Track(
        job_id=job.id,
        release_id=release.id,
        source="slskd",
        title="Song",
        artist="Artist",
        album_artist="Artist",
        album="Album",
        year="2000",
        disc=1,
        disc_total=1,
        track_no=1,
        staging_path=str(staged),
        source_path=str(staged),
        import_state=ImportWorkflowState.ready,
    )
    db_session.add(track)
    await db_session.flush()
    destination = tmp_path / "library" / "Artist" / "2000 - Album" / "01 - Song.wav"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old preferred file")
    plans = await plan_release_import(db_session, release, library_root=tmp_path / "library")
    plans[0].status = ImportWorkflowState.ready
    plans[0].collision_state = CollisionState.clear
    with pytest.raises(ImportExecutionError, match="tag readback failed"):
        await execute_release_import(
            db_session, release, library_root=tmp_path / "library", replace_existing_verified=True
        )
    assert destination.read_bytes() == b"old preferred file"
