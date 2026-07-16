from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import no_type_check

from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_plan import CollisionState, ImportPlan, TagVerificationState
from app.models.release import Release
from app.models.track import Track
from app.models.workflow import ImportWorkflowState
from app.naming.convention import NamingError, render_path

_DESTINATION_TEMPLATE = "{album_artist}/{year} - {album}/{disc_track} - {title}.{ext}"


class ImportPlanningError(ValueError):
    pass


class ImportExecutionError(RuntimeError):
    pass


def _resolved_path(path: Path) -> Path:
    return path.resolve()


def _path_exists(path: Path) -> bool:
    return path.exists()


def _unlink_missing_ok(path: Path) -> None:
    path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_regular_source(path: Path) -> None:
    if path.is_symlink():
        raise ImportPlanningError("source path is a symlink")
    if not path.is_file():
        raise ImportPlanningError("source path is not a regular file")


def _destination_inside_root(library_root: Path, destination: Path) -> None:
    root = library_root.resolve()
    resolved = destination.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ImportPlanningError("destination escapes library root")


def _existing_parent_symlink(library_root: Path, destination: Path) -> Path | None:
    root = library_root.resolve()
    current = root
    for part in destination.relative_to(root).parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            return current
    return None


def _track_source_path(track: Track) -> Path:
    raw = track.staging_path or track.source_path
    if not raw:
        raise ImportPlanningError(f"track {track.id} has no staged source path")
    return Path(raw)


def _tags_for(release: Release, track: Track) -> dict[str, str]:
    tags = {
        "title": track.title or "",
        "artist": track.artist or "",
        "album": track.album or release.title or "",
        "album_artist": track.album_artist or release.album_artist or track.artist or "",
        "date": track.year or release.year or "",
        "tracknumber": str(track.track_no or ""),
        "discnumber": str(track.disc or ""),
        "musicbrainz_trackid": track.mbid or "",
        "musicbrainz_albumid": release.release_mbid or "",
    }
    return {key: value for key, value in tags.items() if value}


class MutagenTagWriter:
    @no_type_check
    def write_and_verify(self, path: Path, tags: dict[str, str]) -> bool:
        if path.suffix.casefold() != ".mp3":
            return True
        id3 = ID3()
        if title := tags.get("title"):
            id3.add(TIT2(encoding=3, text=title))
        if artist := tags.get("artist"):
            id3.add(TPE1(encoding=3, text=artist))
        if album := tags.get("album"):
            id3.add(TALB(encoding=3, text=album))
        if album_artist := tags.get("album_artist"):
            id3.add(TPE2(encoding=3, text=album_artist))
        if date := tags.get("date"):
            id3.add(TDRC(encoding=3, text=date))
        if tracknumber := tags.get("tracknumber"):
            id3.add(TRCK(encoding=3, text=tracknumber))
        if discnumber := tags.get("discnumber"):
            id3.add(TPOS(encoding=3, text=discnumber))
        if recording := tags.get("musicbrainz_trackid"):
            id3.add(TXXX(encoding=3, desc="MusicBrainz Track Id", text=recording))
        if release := tags.get("musicbrainz_albumid"):
            id3.add(TXXX(encoding=3, desc="MusicBrainz Album Id", text=release))
        id3.save(path, v2_version=3)
        readback = self.read_tags(path)
        return all(readback.get(key) == value for key, value in tags.items())

    @no_type_check
    def read_tags(self, path: Path) -> dict[str, str]:
        if path.suffix.casefold() != ".mp3":
            return {}
        id3 = ID3(path)
        values: dict[str, str] = {}
        frame_map = {
            "title": "TIT2",
            "artist": "TPE1",
            "album": "TALB",
            "album_artist": "TPE2",
            "date": "TDRC",
            "tracknumber": "TRCK",
            "discnumber": "TPOS",
        }
        for key, frame_id in frame_map.items():
            frame = id3.get(frame_id)
            if frame is not None and getattr(frame, "text", None):
                values[key] = str(frame.text[0])
        for frame in id3.getall("TXXX"):
            desc = frame.desc.casefold()
            if frame.text and desc == "musicbrainz track id":
                values["musicbrainz_trackid"] = str(frame.text[0])
            if frame.text and desc == "musicbrainz album id":
                values["musicbrainz_albumid"] = str(frame.text[0])
        return values


async def plan_release_import(
    db: AsyncSession,
    release: Release,
    *,
    library_root: Path,
    naming_template: str = _DESTINATION_TEMPLATE,
) -> list[ImportPlan]:
    await db.execute(delete(ImportPlan).where(ImportPlan.release_id == release.id))
    await db.flush()
    tracks_result = await db.execute(
        select(Track).where(Track.release_id == release.id).order_by(Track.track_no, Track.id)
    )
    tracks = list(tracks_result.scalars().all())

    library_root = _resolved_path(library_root)
    plans: list[ImportPlan] = []
    for track in tracks:
        source = _track_source_path(track)
        status = ImportWorkflowState.ready
        collision = CollisionState.clear
        error: str | None = None
        source_hash: str | None = None
        operations: list[str] = [
            "hash-source",
            "copy-to-destination-filesystem-temp",
            "fsync-temp",
            "tag-and-readback",
            "recheck-destination",
            "atomic-rename",
            "fsync-destination-directory",
            "retain-staged-source",
        ]

        try:
            _ensure_regular_source(source)
            source_hash = _sha256(source)
            relative = render_path(track, template=naming_template)
            destination = library_root / relative
            symlink_parent = _existing_parent_symlink(library_root, destination)
            if symlink_parent is not None:
                raise ImportPlanningError(f"destination parent is a symlink: {symlink_parent}")
            _destination_inside_root(library_root, destination)
            if destination.exists():
                destination_hash = _sha256(destination) if destination.is_file() else None
                status = ImportWorkflowState.needs_review
                if destination_hash == source_hash:
                    collision = CollisionState.duplicate
                    error = "destination already contains same bytes"
                else:
                    collision = CollisionState.conflict
                    error = "destination already exists with different bytes"
            else:
                existing = await db.execute(
                    select(Track).where(Track.content_sha256 == source_hash, Track.id != track.id)
                )
                if existing.scalars().first() is not None:
                    status = ImportWorkflowState.needs_review
                    collision = CollisionState.duplicate
                    error = "same content hash already belongs to another track"
        except (ImportPlanningError, NamingError, OSError) as exc:
            try:
                relative = render_path(track)
            except NamingError:
                relative = f"track-{track.id or 'unknown'}"
            destination = library_root / relative
            status = ImportWorkflowState.needs_review
            collision = CollisionState.needs_review
            error = str(exc)

        track.content_sha256 = source_hash
        track.import_state = status
        plan = ImportPlan(
            release_id=release.id,
            track_id=track.id,
            source_path=str(source),
            staging_path=track.staging_path,
            destination_path=str(destination),
            planned_operations_json=json.dumps(operations),
            collision_state=collision,
            tag_verification_state=TagVerificationState.pending,
            status=status,
            error_detail=error,
        )
        db.add(plan)
        plans.append(plan)

    release.import_state = (
        ImportWorkflowState.ready
        if plans and all(plan.status == ImportWorkflowState.ready for plan in plans)
        else ImportWorkflowState.needs_review
    )
    await db.flush()
    return plans


def _copy_to_temp(source: Path, destination: Path, expected_hash: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=destination.suffix
    )
    temp_path = Path(raw_name)
    try:
        with os.fdopen(fd, "wb") as temp, source.open("rb") as src:
            shutil.copyfileobj(src, temp, length=1024 * 1024)
            temp.flush()
            os.fsync(temp.fileno())
        if _sha256(temp_path) != expected_hash:
            raise ImportExecutionError(
                "short copy or checksum mismatch while staging destination temp"
            )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


async def execute_release_import(
    db: AsyncSession,
    release: Release,
    *,
    library_root: Path,
    tag_writer: MutagenTagWriter | None = None,
    before_commit: Callable[[Path], None] | None = None,
) -> list[ImportPlan]:
    tag_writer = tag_writer or MutagenTagWriter()
    plans_result = await db.execute(
        select(ImportPlan).where(ImportPlan.release_id == release.id).order_by(ImportPlan.id)
    )
    plans = list(plans_result.scalars().all())
    if not plans:
        plans = await plan_release_import(db, release, library_root=library_root)
    if any(plan.status != ImportWorkflowState.ready for plan in plans):
        raise ImportExecutionError("release has import plans that are not ready")

    created_destinations: list[Path] = []
    temp_paths: list[Path] = []
    release.import_state = ImportWorkflowState.importing
    for plan in plans:
        plan.status = ImportWorkflowState.importing
    await db.flush()

    try:
        for plan in plans:
            track = plan.track
            if track is None:
                raise ImportExecutionError("import plan is missing a track")
            source = Path(plan.source_path)
            destination = Path(plan.destination_path)
            _destination_inside_root(library_root, destination)
            if _path_exists(destination):
                raise ImportExecutionError("destination exists before import commit")
            expected_hash = track.content_sha256 or _sha256(source)
            temp = _copy_to_temp(source, destination, expected_hash)
            temp_paths.append(temp)
            plan.destination_temp_path = str(temp)
            if not tag_writer.write_and_verify(temp, _tags_for(release, track)):
                plan.tag_verification_state = TagVerificationState.failed
                raise ImportExecutionError("tag readback failed")
            plan.tag_verification_state = TagVerificationState.verified
            if before_commit is not None:
                before_commit(destination)
            if _path_exists(destination):
                raise ImportExecutionError("destination appeared before atomic rename")
            os.replace(temp, destination)
            _fsync_directory(destination.parent)
            temp_paths.remove(temp)
            created_destinations.append(destination)
            track.import_state = ImportWorkflowState.imported
            track.content_sha256 = _sha256(destination)
            plan.status = ImportWorkflowState.imported
            plan.collision_state = CollisionState.clear
        release.import_state = ImportWorkflowState.imported
        await db.flush()
        return plans
    except Exception as exc:
        for temp in temp_paths:
            temp.unlink(missing_ok=True)
        for destination in reversed(created_destinations):
            destination.unlink(missing_ok=True)
        detail = str(exc)
        release.import_state = ImportWorkflowState.rolled_back
        release.rollback_detail = detail
        for plan in plans:
            if plan.status == ImportWorkflowState.imported:
                plan.status = ImportWorkflowState.rolled_back
                plan.rollback_detail = detail
            elif plan.status == ImportWorkflowState.importing:
                plan.status = ImportWorkflowState.failed
                plan.error_detail = detail
            if plan.destination_temp_path:
                _unlink_missing_ok(Path(plan.destination_temp_path))
        tracks_result = await db.execute(select(Track).where(Track.release_id == release.id))
        for track in tracks_result.scalars().all():
            if track.import_state == ImportWorkflowState.imported:
                track.import_state = ImportWorkflowState.rolled_back
        await db.flush()
        if isinstance(exc, ImportExecutionError):
            raise
        raise ImportExecutionError(detail) from exc
