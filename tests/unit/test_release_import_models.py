from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_plan import CollisionState, ImportPlan, TagVerificationState
from app.models.job import Job, JobStatus
from app.models.monitoring import MonitoringRecord, MonitoringStatus
from app.models.release import Release
from app.models.release_candidate import ReleaseCandidate
from app.models.track import Track
from app.models.workflow import AcquisitionState, ImportWorkflowState


async def test_release_candidate_import_and_monitoring_state_persist(
    db_session: AsyncSession,
) -> None:
    job = Job(source="slskd", query="artist album", status=JobStatus.pending)
    db_session.add(job)
    await db_session.flush()

    release = Release(
        job_id=job.id,
        source="slskd",
        title="Album",
        album_artist="Artist",
        release_mbid="11111111-1111-1111-1111-111111111111",
        import_state=ImportWorkflowState.staged,
        staging_path="/staging/slskd/release-1",
    )
    db_session.add(release)
    await db_session.flush()

    track = Track(
        job_id=job.id,
        release_id=release.id,
        title="Song",
        source="slskd",
        acquisition_state=AcquisitionState.downloaded,
        import_state=ImportWorkflowState.staged,
        staging_path="/staging/slskd/release-1/01.flac",
        content_sha256="a" * 64,
    )
    db_session.add(track)
    await db_session.flush()

    candidate = ReleaseCandidate(
        release_id=release.id,
        track_id=track.id,
        recording_mbid="22222222-2222-2222-2222-222222222222",
        release_mbid=release.release_mbid,
        medium_position=1,
        track_position=1,
        track_count=10,
        match_score=0.91,
        match_reasons_json='["recording and release evidence agree"]',
        selected=True,
    )
    plan = ImportPlan(
        release_id=release.id,
        track_id=track.id,
        source_path=track.staging_path,
        staging_path=track.staging_path,
        destination_path="Artist/2026 - Album/01 - Song.flac",
        planned_operations_json='["copy-to-destination-temp", "atomic-rename"]',
        status=ImportWorkflowState.ready,
        collision_state=CollisionState.clear,
        tag_verification_state=TagVerificationState.pending,
    )
    monitor = MonitoringRecord(
        release_id=release.id,
        status=MonitoringStatus.active,
        desired_quality_json='{"codec":"flac"}',
    )
    db_session.add_all([candidate, plan, monitor])
    await db_session.commit()

    saved = (
        await db_session.execute(select(Release).where(Release.id == release.id))
    ).scalar_one()

    assert saved.import_state == ImportWorkflowState.staged
    assert saved.candidates[0].match_score == 0.91
    assert saved.import_plans[0].collision_state == CollisionState.clear
    assert saved.monitoring_records[0].status == MonitoringStatus.active
