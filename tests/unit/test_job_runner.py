from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.jobs import runner
from app.models.job import Job, JobStatus
from app.models.track import IdentityResolutionState, Track
from app.naming.convention import NamingError
from app.schemas.search import SearchResult
from app.sources.base import CapabilityState


async def _create_job(db_session: AsyncSession, source: str = "youtube") -> Job:
    job = Job(source=source, query="test query", status=JobStatus.pending)
    db_session.add(job)
    await db_session.flush()
    return job


async def test_run_job_marks_failed_when_result_processing_fails(
    db_session: AsyncSession, test_settings: Settings, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    job = await _create_job(db_session)

    async def fake_fetch_results(job: Job, cfg: Settings) -> Sequence[SearchResult]:
        return [
            SearchResult(source="youtube", title="Song", artist="Artist", url="/tmp/song.flac")
        ]

    async def fail_musicbrainz(track: Track, cfg: Settings) -> None:
        raise RuntimeError("metadata boom")

    mp.setattr(runner, "_fetch_results", fake_fetch_results)
    mp.setattr(runner, "_enrich_musicbrainz", fail_musicbrainz)

    await runner.run_job(job.id, db_session, test_settings)

    assert job.status == JobStatus.failed
    assert job.result_json is not None
    assert "metadata boom" in job.result_json


async def test_prowlarr_result_is_enqueued_to_sabnzbd(
    db_session: AsyncSession, test_settings: Settings, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    job = await _create_job(db_session, source="prowlarr")
    calls: list[str] = []

    async def fake_fetch_results(job: Job, cfg: Settings) -> Sequence[SearchResult]:
        return [
            SearchResult(
                source="prowlarr",
                title="Artist - Album",
                url="https://indexer.local/file.nzb",
                format="nzb",
            )
        ]

    async def noop(track: Track, cfg: Settings) -> None:
        return None

    async def noop_preview(track: Track, db: AsyncSession, cfg: Settings) -> None:
        return None

    class FakeSabnzbdAdapter:
        def __init__(self, base_url: str, api_key: str) -> None:
            calls.append(f"configured:{base_url}:{api_key}")

        async def enqueue(self, nzb_url: str, name: str | None = None) -> str:
            calls.append(f"enqueue:{nzb_url}:{name}")
            return "SAB123"

        async def status(self, nzo_id: str) -> CapabilityState:
            calls.append(f"status:{nzo_id}")
            return CapabilityState(available=True, reason="Downloading")

    mp.setattr(runner, "_fetch_results", fake_fetch_results)
    mp.setattr(runner, "_enrich_musicbrainz", noop)
    mp.setattr(runner, "_enrich_deezer", noop)
    mp.setattr(runner, "_run_fingerprint", noop)
    mp.setattr(runner, "_compute_path_preview", noop_preview)
    mp.setattr(runner, "SabnzbdAdapter", FakeSabnzbdAdapter)

    await runner.run_job(job.id, db_session, test_settings)

    track = (await db_session.execute(select(Track))).scalar_one()
    assert job.status == JobStatus.done
    assert track.source_job_id == "SAB123"
    assert track.source_status == "Downloading"
    assert calls[-2:] == ["enqueue:https://indexer.local/file.nzb:Artist - Album", "status:SAB123"]


async def test_path_preview_naming_error_marks_job_failed(
    db_session: AsyncSession, test_settings: Settings, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    job = await _create_job(db_session)

    async def fake_fetch_results(job: Job, cfg: Settings) -> Sequence[SearchResult]:
        return [
            SearchResult(source="youtube", title="Song", artist="Artist", url="/tmp/song.flac")
        ]

    async def noop(track: Track, cfg: Settings) -> None:
        return None

    def fail_render_path(*args: object, **kwargs: object) -> str:
        raise NamingError("bad naming")

    mp.setattr(runner, "_fetch_results", fake_fetch_results)
    mp.setattr(runner, "_enrich_musicbrainz", noop)
    mp.setattr(runner, "_enrich_deezer", noop)
    mp.setattr(runner, "_run_fingerprint", noop)
    mp.setattr(runner, "render_path", fail_render_path)

    await runner.run_job(job.id, db_session, test_settings)

    assert job.status == JobStatus.failed
    assert job.result_json is not None
    assert "bad naming" in job.result_json


async def test_prowlarr_rejects_non_nzb_and_loopback_urls(
    test_settings: Settings, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    calls: list[str] = []

    class FakeSabnzbdAdapter:
        def __init__(self, base_url: str, api_key: str) -> None:
            pass

        async def enqueue(self, nzb_url: str, name: str | None = None) -> str:
            calls.append(nzb_url)
            return "SAB123"

        async def status(self, nzo_id: str) -> CapabilityState:
            return CapabilityState(available=True, reason="Downloading")

    mp.setattr(runner, "SabnzbdAdapter", FakeSabnzbdAdapter)
    invalid_results = [
        SearchResult(
            source="prowlarr",
            title="Magnet",
            url="magnet:?xt=urn:btih:abc",
            format="nzb",
        ),
        SearchResult(
            source="prowlarr",
            title="Localhost",
            url="http://127.0.0.1/file.nzb",
            format="nzb",
        ),
        SearchResult(
            source="prowlarr",
            title="Html",
            url="https://indexer.local/file.html",
            format="html",
        ),
    ]

    for result in invalid_results:
        try:
            await runner._prepare_acquisition(result, "prowlarr", test_settings)
        except RuntimeError as exc:
            assert "NZB" in str(exc) or "URL" in str(exc)
        else:
            raise AssertionError(f"accepted invalid result: {result.url}")

    assert calls == []


async def test_musicbrainz_empty_result_marks_track_unresolved(
    db_session: AsyncSession, test_settings: Settings, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    mp = monkeypatch
    assert isinstance(mp, MonkeyPatch)
    job = await _create_job(db_session)
    track = Track(job_id=job.id, title="No Match", source="youtube")
    db_session.add(track)
    await db_session.flush()

    class EmptyMusicBrainzClient:
        def __init__(self, user_agent: str) -> None:
            pass

        async def search_recording(
            self, title: str, artist: str | None = None, album: str | None = None
        ) -> list[object]:
            return []

    mp.setattr(runner, "MusicBrainzClient", EmptyMusicBrainzClient)

    await runner._enrich_musicbrainz(track, test_settings)

    assert track.mbid is None
    assert track.identity_state == IdentityResolutionState.unresolved
