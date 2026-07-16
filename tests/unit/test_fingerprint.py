from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.fingerprint.acoustid import fingerprint_file, lookup_acoustid


class TestFingerprintFile:
    async def test_fpcalc_absent_returns_none(self, tmp_path: Path) -> None:
        dummy = tmp_path / "song.flac"
        dummy.write_bytes(b"fake audio")
        with patch("shutil.which", return_value=None):
            result = await fingerprint_file(dummy)
        assert result is None

    async def test_fpcalc_parses_valid_json(self, tmp_path: Path) -> None:
        dummy = tmp_path / "song.flac"
        dummy.write_bytes(b"fake audio")
        output = json.dumps({"duration": 214.3, "fingerprint": "AQAATESTFP"}).encode()

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(output, b""))

        with (
            patch("shutil.which", return_value="/usr/bin/fpcalc"),
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
        ):
            result = await fingerprint_file(dummy)

        assert result is not None
        duration, fp = result
        assert duration == 214
        assert fp == "AQAATESTFP"

    async def test_nonzero_exit_returns_none(self, tmp_path: Path) -> None:
        dummy = tmp_path / "song.flac"
        dummy.write_bytes(b"fake audio")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with (
            patch("shutil.which", return_value="/usr/bin/fpcalc"),
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
        ):
            result = await fingerprint_file(dummy)

        assert result is None

    async def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.flac"
        with patch("shutil.which", return_value="/usr/bin/fpcalc"):
            result = await fingerprint_file(missing)
        assert result is None


class TestLookupAcoustid:
    async def test_no_api_key_returns_empty(self) -> None:
        result = await lookup_acoustid(214, "AQAAFP", "")
        assert result == []

    async def test_returns_mbids_above_threshold(self, httpx_mock: object) -> None:
        from pytest_httpx import HTTPXMock

        mock: HTTPXMock = httpx_mock  # type: ignore[assignment]
        mock.add_response(
            url="https://api.acoustid.org/v2/lookup",
            method="POST",
            json={
                "status": "ok",
                "results": [
                    {
                        "score": 0.9,
                        "recordings": [{"id": "mbid-0001"}],
                    },
                    {
                        "score": 0.4,
                        "recordings": [{"id": "mbid-0002"}],
                    },
                ],
            },
        )
        result = await lookup_acoustid(214, "AQAAFP", "testkey")
        assert result == ["mbid-0001"]

    async def test_empty_results_returns_empty(self, httpx_mock: object) -> None:
        from pytest_httpx import HTTPXMock

        mock: HTTPXMock = httpx_mock  # type: ignore[assignment]
        mock.add_response(
            url="https://api.acoustid.org/v2/lookup",
            method="POST",
            json={"status": "ok", "results": []},
        )
        result = await lookup_acoustid(214, "AQAAFP", "testkey")
        assert result == []
