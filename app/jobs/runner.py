from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.fingerprint.acoustid import fingerprint_file, lookup_acoustid
from app.metadata.deezer import DeezerClient
from app.metadata.musicbrainz import MusicBrainzClient
from app.models.job import Job, JobStatus
from app.models.path_preview import PathPreview
from app.models.track import FingerprintState, IdentityResolutionState, Track
from app.naming.convention import NamingError, render_path
from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import SourceAdapter
from app.sources.prowlarr import ProwlarrAdapter
from app.sources.sabnzbd import SabnzbdAdapter
from app.sources.slskd import SlskdAdapter
from app.sources.youtube import YouTubeAdapter

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def run_job(job_id: int, db: AsyncSession, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()

    job = await db.get(Job, job_id)
    if job is None:
        logger.error("Job %d not found", job_id)
        return

    job.status = JobStatus.running
    job.updated_at = _now()
    await db.flush()

    try:
        results = await _fetch_results(job, cfg)
        tracks_created = 0
        failures: list[str] = []
        for result in results:
            try:
                source_job_id, source_status = await _prepare_acquisition(result, job.source, cfg)
                track = Track(
                    job_id=job_id,
                    title=result.title,
                    artist=result.artist,
                    album_artist=result.artist,
                    source_path=result.url,
                    source_job_id=source_job_id,
                    source_status=source_status,
                    source=result.source,
                    fingerprint_state=FingerprintState.pending,
                )
                db.add(track)
                await db.flush()

                await _enrich_musicbrainz(track, cfg)
                await _enrich_deezer(track, cfg)
                await _run_fingerprint(track, cfg)
                await _compute_path_preview(track, db, cfg)

                tracks_created += 1
            except Exception as exc:
                logger.warning("Failed to process result %s: %s", result.url, exc)
                failures.append(str(exc))

        if failures:
            job.status = JobStatus.failed
            job.result_json = json.dumps({"tracks_created": tracks_created, "errors": failures})
        else:
            job.status = JobStatus.done
            job.result_json = json.dumps({"tracks_created": tracks_created})
        job.updated_at = _now()
    except Exception as exc:
        logger.exception("Job %d failed: %s", job_id, exc)
        job.status = JobStatus.failed
        job.result_json = json.dumps({"error": str(exc)})
        job.updated_at = _now()

    await db.flush()


async def _fetch_results(job: Job, cfg: Settings) -> list[SearchResult]:
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
    return await adapter.search(req)


async def _prepare_acquisition(
    result: SearchResult, source: str, cfg: Settings
) -> tuple[str | None, str | None]:
    if source != "prowlarr":
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
    try:
        client = MusicBrainzClient(cfg.musicbrainz_user_agent)
        results = await client.search_recording(
            title=track.title or "",
            artist=track.artist,
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
