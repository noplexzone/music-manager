from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.fingerprint.acoustid import fingerprint_file, lookup_acoustid
from app.metadata.deezer import DeezerClient
from app.metadata.filename_parse import parse_filename
from app.metadata.musicbrainz import MusicBrainzClient
from app.models.job import Job, JobStatus
from app.models.path_preview import PathPreview
from app.models.release import Release
from app.models.track import FingerprintState, IdentityResolutionState, Track
from app.models.workflow import AcquisitionState
from app.naming.convention import NamingError, render_path
from app.schemas.search import SearchRequest, SearchResult
from app.settings_service import DEFAULT_FREE_TEXT_RESULT_LIMIT
from app.sources.base import SourceAdapter
from app.sources.prowlarr import ProwlarrAdapter
from app.sources.sabnzbd import SabnzbdAdapter
from app.sources.slskd import SlskdAdapter
from app.sources.youtube import ProviderError, YouTubeAdapter

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def run_job(
    job_id: int, db: AsyncSession | None = None, settings: Settings | None = None
) -> None:
    cfg = settings or get_settings()
    if db is None:
        factory = get_session_factory()
        async with factory() as session:
            try:
                await _run_job_in_session(job_id, session, cfg)
                await session.commit()
            except asyncio.CancelledError:
                await session.commit()
                raise
            except Exception:
                await session.rollback()
                raise
        return

    await _run_job_in_session(job_id, db, cfg)


async def _run_job_in_session(job_id: int, db: AsyncSession, cfg: Settings) -> None:
    job = await db.get(Job, job_id)
    if job is None:
        logger.error("Job %d not found", job_id)
        return

    job.status = JobStatus.running
    job.updated_at = _now()
    await db.flush()

    try:
        results = _selected_result(job) or await _fetch_results(job, cfg)
        tracks_created = 0
        failures: list[str] = []
        releases: dict[tuple[str | None, str | None], Release] = {}
        for result in results:
            track: Track | None = None
            try:
                release_key = (result.artist, result.album or result.title)
                release = releases.get(release_key)
                if release is None:
                    release = Release(
                        job_id=job_id,
                        source=result.source,
                        title=result.album or result.title,
                        album_artist=result.artist,
                    )
                    db.add(release)
                    await db.flush()
                    releases[release_key] = release

                track = Track(
                    job_id=job_id,
                    release_id=release.id,
                    title=result.title,
                    artist=result.artist,
                    album_artist=result.artist,
                    album=result.album,
                    source_path=None,
                    source=result.source,
                    acquisition_state=AcquisitionState.acquiring,
                    fingerprint_state=FingerprintState.pending,
                )
                db.add(track)
                await db.flush()

                source_job_id, source_status = await _prepare_acquisition(
                    result, job.source, cfg, track
                )
                track.source_job_id = source_job_id
                track.source_status = source_status

                await _enrich_musicbrainz(track, cfg)
                await _enrich_deezer(track, cfg)
                await _run_fingerprint(track, cfg)
                await _compute_path_preview(track, db, cfg)

                tracks_created += 1
            except ProviderError as exc:
                if track is not None:
                    track.acquisition_state = AcquisitionState.failed
                    track.source_status = exc.code
                logger.warning("Provider result processing failed with code %s", exc.code)
                failures.append(json.dumps(exc.details(), sort_keys=True))
            except Exception:
                if track is not None:
                    track.acquisition_state = AcquisitionState.failed
                logger.warning("Result processing failed")
                failures.append("result_processing_failed")

        if failures and tracks_created:
            job.status = JobStatus.partial
            job.result_json = json.dumps({"tracks_created": tracks_created, "errors": failures})
        elif failures:
            job.status = JobStatus.failed
            job.result_json = json.dumps({"tracks_created": tracks_created, "errors": failures})
        else:
            job.status = JobStatus.done
            job.result_json = json.dumps({"tracks_created": tracks_created})
        job.updated_at = _now()
    except ProviderError as exc:
        logger.warning("Job %d provider failure code %s", job_id, exc.code)
        job.status = JobStatus.failed
        job.result_json = json.dumps({"error": exc.details()})
        job.updated_at = _now()
    except asyncio.CancelledError:
        job.status = JobStatus.cancelled
        tracks = (await db.execute(select(Track).where(Track.job_id == job.id))).scalars()
        for track in tracks:
            if track.acquisition_state in {
                AcquisitionState.queued,
                AcquisitionState.searching,
                AcquisitionState.acquiring,
            }:
                track.acquisition_state = AcquisitionState.cancelled
        job.result_json = json.dumps(
            {"error": {"code": "cancelled", "operation": "job", "retryable": True}}
        )
        job.updated_at = _now()
        await db.flush()
        raise
    except Exception:
        logger.error("Job %d failed", job_id)
        job.status = JobStatus.failed
        job.result_json = json.dumps(
            {"error": {"code": "job_failed", "operation": "job", "retryable": True}}
        )
        job.updated_at = _now()

    await db.flush()


def _selected_result(job: Job) -> list[SearchResult] | None:
    if not job.selected_result_json:
        return None
    return [SearchResult.model_validate(json.loads(job.selected_result_json))]


async def _fetch_results(
    job: Job, cfg: Settings, limit: int = DEFAULT_FREE_TEXT_RESULT_LIMIT
) -> list[SearchResult]:
    req = SearchRequest(query=job.query, sources=[job.source])
    adapter: SourceAdapter
    if job.source == "slskd":
        adapter = SlskdAdapter(cfg.slskd_url, cfg.slskd_api_key)
    elif job.source == "prowlarr":
        adapter = ProwlarrAdapter(cfg.prowlarr_url, cfg.prowlarr_api_key)
    elif job.source == "youtube":
        adapter = YouTubeAdapter(cfg.ytdlp_cookies_file)
    else:
        raise ValueError(f"Unknown source: {job.source}")
    return (await adapter.search(req))[:limit]


async def _prepare_acquisition(
    result: SearchResult, source: str, cfg: Settings, track: Track | None = None
) -> tuple[str | None, str | None]:
    if source == "youtube":
        if not result.url:
            raise ProviderError("invalid_result", "YouTube result URL is missing", "acquire")
        acquired = await YouTubeAdapter(cfg.ytdlp_cookies_file).acquire(
            result.url, cfg.staging_root
        )
        if track is not None:
            track.source_path = str(acquired.path)
            track.staging_path = str(acquired.path)
            track.acquisition_state = AcquisitionState.downloaded
            track.acquisition_provenance_json = json.dumps(acquired.provenance, sort_keys=True)
        return None, "downloaded"
    if source == "slskd":
        username = str(result.metadata.get("username") or "")
        filename = str(result.metadata.get("filename") or "")
        transfer_id = await SlskdAdapter(cfg.slskd_url, cfg.slskd_api_key).enqueue(
            username, filename, result.size_bytes
        )
        if track is not None:
            safe_name = Path(filename.replace("\\", "/")).name
            staging_path = cfg.staging_root / safe_name
            track.source_path = str(staging_path)
            track.staging_path = str(staging_path)
            track.acquisition_state = AcquisitionState.acquiring
            track.acquisition_provenance_json = json.dumps(
                {"source": "slskd", "username": username, "filename": filename}, sort_keys=True
            )
        return transfer_id, "queued"
    if source != "prowlarr":
        if track is not None:
            track.source_path = result.url
        return None, None
    nzb_url = _validated_nzb_url(result, cfg)

    sab = SabnzbdAdapter(cfg.sabnzbd_url, cfg.sabnzbd_api_key)
    sab_job_id = await sab.enqueue(nzb_url, name=result.title)
    if not sab_job_id:
        raise RuntimeError("SABnzbd enqueue returned no job id")
    state = await sab.status(sab_job_id)
    if not state.available:
        raise RuntimeError(f"SABnzbd job status unavailable: {state.reason}")
    return sab_job_id, state.reason


def _validated_nzb_url(result: SearchResult, cfg: Settings) -> str:
    if result.format != "nzb" or not result.url:
        raise RuntimeError("Prowlarr result is not a validated NZB URL")

    parsed = urlparse(result.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("Prowlarr result has invalid NZB URL")
    if not parsed.path.endswith(".nzb"):
        raise RuntimeError("Prowlarr result URL is not an NZB")
    trusted = _trusted_prowlarr_origin(cfg)
    result_origin = _origin_tuple(parsed)
    if trusted is None:
        raise RuntimeError("Prowlarr trusted NZB URL host is not configured")
    if result_origin != trusted:
        raise RuntimeError("Prowlarr result URL host is not trusted")
    return result.url


def _trusted_prowlarr_origin(cfg: Settings) -> tuple[str, str, int | None] | None:
    parsed = urlparse(cfg.prowlarr_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return _origin_tuple(parsed)


def _origin_tuple(parsed: ParseResult) -> tuple[str, str, int | None]:
    if parsed.hostname is None:
        raise RuntimeError("Prowlarr result has invalid NZB URL")
    return (parsed.scheme.casefold(), parsed.hostname.casefold().rstrip("."), parsed.port)


async def _enrich_musicbrainz(track: Track, cfg: Settings) -> None:
    if not track.title:
        return
    started = _now()
    guess = parse_filename(str(track.title))
    title = guess.title
    artist = track.artist or (guess.artist if guess.confidence >= 0.65 else None)
    if guess.confidence < 0.25:
        track.identity_state = IdentityResolutionState.unresolved
        logger.info(
            "Skipping MusicBrainz enrichment for low-confidence parse on track %s", track.id
        )
        return
    try:
        client = MusicBrainzClient(cfg.musicbrainz_user_agent)
        results = await client.search_recording(
            title=title,
            artist=artist,
            album=track.album or (guess.album if guess.confidence >= 0.8 else None),
        )
        if results:
            meta = results[0]
            track.mbid = track.mbid or meta.mbid
            track.identity_state = IdentityResolutionState.resolved
            track.title = track.title or meta.title
            track.artist = track.artist or meta.artist
            track.album_artist = track.album_artist or meta.album_artist
            track.album = track.album or meta.album
            track.year = track.year or meta.year
            track.disc = track.disc or meta.disc
            track.disc_total = track.disc_total or meta.disc_total
            track.track_no = track.track_no or meta.track_no
            if meta.duration_ms and not track.duration_sec:
                track.duration_sec = meta.duration_ms // 1000
        else:
            track.identity_state = IdentityResolutionState.unresolved
        logger.info(
            "MusicBrainz enrichment for track %s took %.3fs",
            track.id,
            (_now() - started).total_seconds(),
        )
    except Exception as exc:
        track.identity_state = IdentityResolutionState.unresolved
        logger.warning("MusicBrainz enrichment failed for track %d: %s", track.id, exc)


async def _enrich_deezer(track: Track, cfg: Settings) -> None:
    if not track.title:
        return
    try:
        client = DeezerClient(cfg.deezer_api_url)
        results = await client.search_track(track.title or "", track.artist)
        if results:
            d = results[0]
            track.deezer_id = track.deezer_id or d.deezer_id
            if not track.duration_sec and d.duration_sec:
                track.duration_sec = d.duration_sec
    except Exception as exc:
        logger.warning("Deezer enrichment failed for track %d: %s", track.id, exc)


async def _run_fingerprint(track: Track, cfg: Settings) -> None:
    if not track.source_path:
        track.fingerprint_state = FingerprintState.skipped
        return
    path = Path(track.source_path)
    if not await asyncio.to_thread(path.exists):
        track.fingerprint_state = FingerprintState.skipped
        return

    result = await fingerprint_file(path)
    if result is None:
        import shutil

        if not shutil.which("fpcalc"):
            track.fingerprint_state = FingerprintState.skipped
        else:
            track.fingerprint_state = FingerprintState.failed
        return

    duration, fingerprint = result
    track.acoustid = fingerprint
    if not track.duration_sec:
        track.duration_sec = duration
    track.fingerprint_state = FingerprintState.done

    if cfg.acoustid_api_key and not track.mbid:
        mbids = await lookup_acoustid(duration, fingerprint, cfg.acoustid_api_key)
        if mbids:
            track.mbid = mbids[0]
            track.identity_state = IdentityResolutionState.resolved


async def _compute_path_preview(track: Track, db: AsyncSession, cfg: Settings) -> None:
    try:
        rendered = render_path(
            track,
            title=track.title or "Unknown",
            ext=_guess_ext(track.source_path),
            template=cfg.naming_template,
            library_root=cfg.library_root,
        )
        preview = PathPreview(
            track_id=track.id,
            rendered_path=rendered,
            naming_template=cfg.naming_template,
            computed_at=_now(),
        )
        db.add(preview)
        await db.flush()
    except NamingError as exc:
        logger.warning("Path preview failed for track %d: %s", track.id, exc)
        raise


def _guess_ext(source_path: str | None) -> str:
    if source_path and "." in source_path.rsplit("/", 1)[-1]:
        return source_path.rsplit(".", 1)[-1].lower()
    return "flac"
