from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_FPCALC_TIMEOUT = 30
_ACOUSTID_API = "https://api.acoustid.org/v2/lookup"
_SCORE_THRESHOLD = 0.6


async def fingerprint_file(path: Path) -> tuple[int, str] | None:
    """Run fpcalc on a file and return (duration_sec, fingerprint).

    Returns None if fpcalc is absent, the file is unreadable, or fpcalc fails.
    """
    fpcalc = shutil.which("fpcalc")
    if not fpcalc:
        logger.warning("fingerprinting skipped: fpcalc not found")
        return None

    exists, is_file = await asyncio.to_thread(lambda: (path.exists(), path.is_file()))
    if not exists or not is_file:
        logger.warning("fingerprinting failed: file not found: %s", path)
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            fpcalc,
            "-json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_FPCALC_TIMEOUT)
    except TimeoutError:
        logger.warning("fingerprinting failed: fpcalc timed out for %s", path)
        return None
    except Exception as exc:
        logger.warning("fingerprinting failed: %s", exc)
        return None

    if proc.returncode != 0:
        logger.warning("fpcalc exited %d for %s: %s", proc.returncode, path, stderr.decode())
        return None

    try:
        data = json.loads(stdout.decode())
        duration = int(float(data["duration"]))
        fingerprint: str = data["fingerprint"]
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("fingerprinting failed: could not parse fpcalc output: %s", exc)
        return None

    return duration, fingerprint


async def lookup_acoustid(duration: int, fingerprint: str, api_key: str) -> list[str]:
    """Return a list of candidate MBIDs from AcoustID, sorted by score descending.

    Returns an empty list if api_key is empty or the lookup fails.
    """
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                _ACOUSTID_API,
                data={
                    "client": api_key,
                    "duration": str(duration),
                    "fingerprint": fingerprint,
                    "meta": "recordings",
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("AcoustID lookup failed: %s", exc)
        return []

    data = resp.json()
    results = data.get("results", [])
    mbids: list[tuple[float, str]] = []
    for result in results:
        score = float(result.get("score", 0.0))
        for recording in result.get("recordings", []):
            rid = recording.get("id")
            if rid and score >= _SCORE_THRESHOLD:
                mbids.append((score, str(rid)))

    mbids.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in mbids]
