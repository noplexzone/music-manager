from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.schemas.search import SearchRequest, SearchResult
from app.sources.base import CapabilityState

_MAX_SEARCH_RESULTS = 20
_DEFAULT_SEARCH_TIMEOUT_SEC = 30.0
_PROCESS_STOP_GRACE_SEC = 2.0
_YTDLP_SOCKET_TIMEOUT_SEC = 15
_HEALTH_PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@dataclass(frozen=True)
class AcquiredMedia:
    path: Path
    provenance: dict[str, object]


@dataclass(frozen=True)
class ProviderError(RuntimeError):
    code: str
    message: str
    operation: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.message

    def details(self) -> dict[str, object]:
        return {
            "code": self.code,
            "operation": self.operation,
            "retryable": self.retryable,
        }


def _ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except ImportError:
        return False


def _ytdlp_version() -> str:
    try:
        return version("yt-dlp")
    except PackageNotFoundError:
        return "unknown"


def _cookie_status(cookie_file: str) -> tuple[bool, str, str]:
    if not cookie_file:
        return (
            True,
            "not_configured",
            "Cookies are not configured; public search remains available",
        )
    path = Path(cookie_file)
    if not path.exists() or not path.is_file():
        return False, "cookies_missing", "Configured cookies file is missing"
    if not os.access(path, os.R_OK):
        return False, "cookies_unreadable", "Configured cookies file is not readable"
    try:
        with path.open(encoding="utf-8") as cookie_stream:
            header = cookie_stream.readline(256).strip()
    except (OSError, UnicodeError):
        return False, "cookies_unreadable", "Configured cookies file is not readable"
    if not header.startswith("# Netscape HTTP Cookie File"):
        return (
            False,
            "cookies_invalid_or_expired",
            "Configured cookies file is not valid Netscape format",
        )
    return True, "configured", "Cookies are configured"


def _classify_failure(stderr: bytes, operation: str = "search") -> ProviderError:
    text = stderr.decode("utf-8", errors="replace").casefold()
    if "sign in" in text or "login" in text or "authentication" in text:
        code, message, retryable = "auth_required", "YouTube authentication is required", False
    elif "rate limit" in text or "too many requests" in text or "http error 429" in text:
        code, message, retryable = (
            "rate_limited",
            "YouTube temporarily rate limited the request",
            True,
        )
    elif "requested format is not available" in text:
        code, message, retryable = (
            "format_unavailable",
            "Requested audio format is unavailable",
            False,
        )
    elif "cookie" in text and ("expired" in text or "invalid" in text):
        code, message, retryable = (
            "cookies_invalid_or_expired",
            "Configured YouTube cookies are invalid or expired",
            False,
        )
    else:
        code, message, retryable = "extractor_error", "YouTube extractor failed", True
    return ProviderError(code, message, operation, retryable)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.communicate(), timeout=_PROCESS_STOP_GRACE_SEC)
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.communicate()


class YouTubeAdapter:
    name = "youtube"

    def __init__(
        self, cookies_file: str = "", search_timeout_sec: float = _DEFAULT_SEARCH_TIMEOUT_SEC
    ) -> None:
        self._cookies_file = cookies_file
        self._search_timeout_sec = search_timeout_sec

    async def health(self) -> CapabilityState:
        if not _ytdlp_available():
            return CapabilityState(
                available=False,
                reason="yt-dlp is not installed",
                extra={"code": "ytdlp_missing", "cookies": "not_probed", "auth": "not_probed"},
            )
        valid, cookie_state, reason = _cookie_status(self._cookies_file)
        details: dict[str, object] = {
            "code": cookie_state,
            "version": _ytdlp_version(),
            "cookies": cookie_state,
            "auth": "not_probed",
            "throttling": "not_probed",
            "audio_formats": "not_probed",
        }
        if not valid:
            return CapabilityState(False, reason, details)
        process = await asyncio.create_subprocess_exec(
            *(self._base_command() + ["--dump-single-json", "--skip-download", _HEALTH_PROBE_URL]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), self._search_timeout_sec
            )
        except TimeoutError:
            await _stop_process(process)
            details.update(code="timeout", auth="unknown", throttling="unknown")
            return CapabilityState(False, "YouTube health probe timed out", details)
        except asyncio.CancelledError:
            await _stop_process(process)
            raise
        if process.returncode != 0:
            failure = _classify_failure(stderr, "health")
            details.update(
                code=failure.code,
                auth="required"
                if failure.code in {"auth_required", "cookies_invalid_or_expired"}
                else "unknown",
                throttling="rate_limited" if failure.code == "rate_limited" else "not_detected",
            )
            return CapabilityState(False, failure.message, details)
        try:
            info = json.loads(stdout)
            formats = info.get("formats", []) if isinstance(info, dict) else []
        except (json.JSONDecodeError, UnicodeDecodeError):
            formats = []
        has_audio = any(
            isinstance(item, dict) and item.get("acodec") not in {None, "none"} for item in formats
        )
        details.update(
            code="ok" if has_audio else "format_unavailable",
            auth="cookie_access_ok" if self._cookies_file else "public_access_ok",
            throttling="not_detected",
            audio_formats="available" if has_audio else "unavailable",
        )
        return CapabilityState(
            has_audio,
            None if has_audio else "No suitable YouTube audio format is available",
            details,
        )

    def _base_command(self) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-warnings",
            "--socket-timeout",
            str(_YTDLP_SOCKET_TIMEOUT_SEC),
        ]
        if self._cookies_file:
            command.extend(["--cookies", self._cookies_file])
        return command

    async def search(self, query: SearchRequest) -> list[SearchResult]:
        if not _ytdlp_available():
            raise ProviderError("ytdlp_missing", "yt-dlp is not installed", "search")
        valid, code, reason = _cookie_status(self._cookies_file)
        if not valid:
            raise ProviderError(code, reason, "search")

        command = self._base_command() + [
            "--dump-single-json",
            "--flat-playlist",
            "--skip-download",
            "--no-warnings",
        ]
        command.append(f"ytsearch{_MAX_SEARCH_RESULTS}:{query.query}")
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._search_timeout_sec
            )
        except TimeoutError as exc:
            await _stop_process(process)
            raise ProviderError("timeout", "YouTube search timed out", "search", True) from exc
        except asyncio.CancelledError:
            await _stop_process(process)
            raise

        if process.returncode != 0:
            raise _classify_failure(stderr)
        try:
            info = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(
                "extractor_error", "YouTube extractor returned invalid data", "search"
            ) from exc
        if not isinstance(info, dict):
            raise ProviderError(
                "extractor_error", "YouTube extractor returned invalid data", "search"
            )
        return self._results(info)

    async def acquire(self, url: str, staging_root: Path) -> AcquiredMedia:
        if not _ytdlp_available():
            raise ProviderError("ytdlp_missing", "yt-dlp is not installed", "acquire")
        parsed = urlparse(url)
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        safe_id = video_id.replace("-", "").replace("_", "")
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"youtube.com", "www.youtube.com"}
            or not safe_id.isalnum()
        ):
            raise ProviderError("invalid_result", "YouTube result URL is invalid", "acquire")
        parent = staging_root / "youtube"
        final_dir = parent / video_id
        temp_dir = parent / f".{video_id}.{uuid.uuid4().hex}.partial"
        staging_root.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded setup
        if staging_root.is_symlink() or (  # noqa: ASYNC240 - reject link escape
            parent.exists() and parent.is_symlink()
        ):
            raise ProviderError("unsafe_staging", "YouTube staging root is unsafe", "acquire")
        if final_dir.exists() or final_dir.is_symlink():
            raise ProviderError(
                "staging_collision", "YouTube staging destination exists", "acquire"
            )
        temp_dir.mkdir(parents=True, exist_ok=False)
        output = temp_dir / "audio.%(ext)s"
        command = self._base_command() + [
            "--no-playlist",
            "--format",
            "bestaudio",
            "--print-json",
            "--output",
            str(output),
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), self._search_timeout_sec
                )
            except TimeoutError as exc:
                await _stop_process(process)
                raise ProviderError(
                    "timeout", "YouTube acquisition timed out", "acquire", True
                ) from exc
            except asyncio.CancelledError:
                await _stop_process(process)
                raise
            if process.returncode != 0:
                raise _classify_failure(stderr, "acquire")
            try:
                info = json.loads(stdout)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderError(
                    "extractor_error", "YouTube extractor returned invalid data", "acquire"
                ) from exc
            artifacts = [
                item
                for item in temp_dir.iterdir()
                if item.is_file() and not item.is_symlink() and ".part" not in item.name
            ]
            if len(artifacts) != 1 or artifacts[0].stat().st_size == 0:
                raise ProviderError(
                    "artifact_invalid",
                    "YouTube acquisition produced no verified audio artifact",
                    "acquire",
                )
            artifact_name = artifacts[0].name
            os.rename(temp_dir, final_dir)
            provenance = {
                "provider": "youtube",
                "video_id": video_id,
                "format_id": info.get("format_id"),
                "extension": info.get("ext"),
                "audio_codec": info.get("acodec"),
                "ytdlp_version": _ytdlp_version(),
                "cookies_used": bool(self._cookies_file),
            }
            return AcquiredMedia(final_dir / artifact_name, provenance)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _results(info: dict[str, Any]) -> list[SearchResult]:
        entries: list[dict[str, Any]] = info.get("entries", []) if info else []
        results: list[SearchResult] = []
        for entry in entries:
            if not entry:
                continue
            duration = entry.get("duration")
            video_id = entry.get("id")
            canonical_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
            results.append(
                SearchResult(
                    source="youtube",
                    title=entry.get("title"),
                    artist=entry.get("channel") or entry.get("uploader"),
                    duration_sec=int(duration) if duration is not None else None,
                    url=canonical_url,
                    metadata={
                        "view_count": entry.get("view_count"),
                        "upload_date": entry.get("upload_date"),
                        "channel": entry.get("channel"),
                        "video_id": video_id,
                        "extractor": entry.get("extractor") or "youtube",
                    },
                )
            )
        return results
