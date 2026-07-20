from __future__ import annotations

import asyncio
import base64
import json
import signal
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.search import SearchRequest
from app.sources.youtube import ProviderError


def _profile(home: Path) -> tuple[Path, Path]:
    home.mkdir(exist_ok=True)
    config = home / ".tidal-dl.json"
    token = home / ".tidal-dl.token.json"
    config.write_text(json.dumps({"audioQuality": "HiFi"}))
    token.write_bytes(
        base64.b64encode(
            json.dumps(
                {
                    "userid": "123",
                    "countryCode": "US",
                    "accessToken": "secret",
                    "refreshToken": "refresh-secret",
                    "expiresAfter": time.time() + 3600,
                }
            ).encode()
        )
    )
    return config, token


async def test_health_is_local_truthful_and_secret_safe(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    with patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"):
        state = await TidalAdapter(str(config), str(token), "HiFi").health()
    assert state.available
    assert state.extra == {
        "code": "ok",
        "version": "2022.10.31.1",
        "profile": "configured",
        "auth": "unprobed",
        "quality": "HiFi",
    }
    assert "secret" not in json.dumps(state.extra)


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("missing", "tidal_dl_missing"),
        ("unset", "profile_unconfigured"),
        ("names", "unsafe_profile_layout"),
        ("parents", "unsafe_profile_layout"),
        ("config", "profile_invalid"),
        ("token", "session_invalid"),
        ("symlink", "unsafe_profile_layout"),
    ],
)
async def test_health_rejects_unsafe_or_invalid_profiles(
    tmp_path: Path, case: str, code: str
) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    version = "2022.10.31.1"
    if case == "missing":
        version = ""
    elif case == "unset":
        config, token = Path("."), Path(".")
    elif case == "names":
        config = config.rename(tmp_path / "secret-config.json")
    elif case == "parents":
        other = tmp_path / "other"
        other.mkdir()
        token = token.rename(other / token.name)
    elif case == "config":
        config.write_text("secret-not-json")
    elif case == "token":
        token.write_text("secret-not-base64-json")
    elif case == "symlink":
        real = tmp_path / "real"
        token.rename(real)
        token.symlink_to(real)
    with patch("app.sources.tidal._tidal_dl_version", return_value=version):
        state = await TidalAdapter(
            "" if case == "unset" else str(config), "" if case == "unset" else str(token)
        ).health()
    assert not state.available
    assert state.extra["code"] == code
    assert "secret" not in (state.reason or "") + json.dumps(state.extra)


@pytest.mark.parametrize(
    "url", ["https://tidal.com/browse/track/123456", "https://listen.tidal.com/track/987"]
)
async def test_search_returns_one_direct_result(tmp_path: Path, url: str) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    results = await TidalAdapter(str(config), str(token)).search(SearchRequest(query=url))
    assert len(results) == 1
    assert results[0].source == "tidal" and results[0].url == url
    assert results[0].metadata == {"track_id": url.rsplit("/", 1)[-1], "direct_url": True}


@pytest.mark.parametrize(
    "url",
    [
        "song",
        "http://tidal.com/browse/track/1",
        "https://evil/tidal.com/browse/track/1",
        "https://tidal.com.evil/browse/track/1",
        "https://u@tidal.com/browse/track/1",
        "https://tidal.com:443/browse/track/1",
        "https://tidal.com/browse/album/1",
        "https://tidal.com/browse/track/x",
        "https://tidal.com/browse/track/1/extra",
        "https://tidal.com/browse/track/1?token=secret",
        "https://listen.tidal.com/track/1#x",
    ],
)
async def test_search_rejects_non_direct_and_deceptive_urls(tmp_path: Path, url: str) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    with pytest.raises(ProviderError) as caught:
        await TidalAdapter(str(config), str(token)).search(SearchRequest(query=url))
    assert caught.value.code == "invalid_url" and "secret" not in caught.value.message


async def test_acquire_exact_argv_env_and_verified_provenance(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path / "home")

    isolated_homes: list[str] = []

    async def spawn(*args: object, **kwargs: object) -> MagicMock:
        output = Path(args[args.index("--output") + 1])
        isolated_home = str(kwargs["env"]["HOME"])
        isolated_homes.append(isolated_home)
        copied_config = Path(isolated_home) / ".tidal-dl.json"
        assert copied_config.read_text() == config.read_text()
        copied_config.write_text('{"downloadPath":"transient"}')
        artifact = output / "Artist" / "Album" / "song.flac"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"audio")
        process = MagicMock(pid=321, returncode=0)
        process.communicate = AsyncMock(return_value=(b"ok", b""))
        return process

    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value="/usr/bin/tidal-dl"),
        patch("app.sources.tidal.asyncio.create_subprocess_exec", side_effect=spawn) as run,
        patch("app.sources.tidal._is_supported_audio", return_value=True),
    ):
        acquired = await TidalAdapter(str(config), str(token), "Master").acquire(
            "https://tidal.com/browse/track/123", tmp_path / "stage"
        )
    args = run.call_args.args
    assert args == (
        sys.executable,
        "-m",
        "app.sources.tidal_runner",
        "--url",
        "https://tidal.com/browse/track/123",
        "--output",
        args[6],
        "--quality",
        "Master",
    )
    kw = run.call_args.kwargs
    assert (
        kw["stdin"] is asyncio.subprocess.DEVNULL
        and kw["start_new_session"] is True
        and kw["env"]["HOME"] != str(tmp_path / "home")
        and "XDG_CONFIG_HOME" not in kw["env"]
        and "shell" not in kw
    )
    assert acquired.path == tmp_path / "stage" / "tidal" / "123" / "Artist" / "Album" / "song.flac"
    assert acquired.provenance == {
        "provider": "tidal",
        "track_id": "123",
        "quality": "Master",
        "tidal_dl_version": "2022.10.31.1",
        "extension": "flac",
    }
    assert "secret" not in json.dumps(acquired.provenance)
    assert json.loads(config.read_text()) == {"audioQuality": "HiFi"}
    assert isolated_homes and not await asyncio.to_thread(Path(isolated_homes[0]).exists)


@pytest.mark.parametrize(
    ("stderr", "code", "retryable"),
    [
        (b"Please login token=secret", "auth_required", False),
        (b"HTTP 429 token=secret", "rate_limited", True),
        (b"quality not available token=secret", "format_unavailable", False),
        (b"boom token=secret", "downloader_error", True),
    ],
)
async def test_acquire_sanitized_failure_classes(
    tmp_path: Path, stderr: bytes, code: str, retryable: bool
) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    process = MagicMock(pid=1, returncode=1)
    process.communicate = AsyncMock(return_value=(b"", stderr))
    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value="tidal-dl"),
        patch("app.sources.tidal.asyncio.create_subprocess_exec", return_value=process),
        pytest.raises(ProviderError) as caught,
    ):
        await TidalAdapter(str(config), str(token)).acquire(
            "https://listen.tidal.com/track/123", tmp_path / "stage"
        )
    assert (
        caught.value.code == code
        and caught.value.retryable is retryable
        and "secret" not in caught.value.message
    )


async def test_acquire_timeout_and_cancel_reap_group(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    for effect, expected in [
        ([asyncio.TimeoutError, (b"", b"")], "timeout"),
        ([asyncio.CancelledError, (b"", b"")], "cancel"),
    ]:
        process = MagicMock(pid=654, returncode=None)
        process.communicate = AsyncMock(side_effect=effect)
        with (
            patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
            patch("app.sources.tidal._tidal_dl_executable", return_value="tidal-dl"),
            patch("app.sources.tidal.asyncio.create_subprocess_exec", return_value=process),
            patch("app.sources.tidal.os.killpg") as killpg,
        ):
            if expected == "timeout":
                with pytest.raises(ProviderError) as caught:
                    await TidalAdapter(str(config), str(token), timeout_sec=0.01).acquire(
                        "https://listen.tidal.com/track/123", tmp_path / "stage"
                    )
                assert caught.value.code == "timeout"
            else:
                with pytest.raises(asyncio.CancelledError):
                    await TidalAdapter(str(config), str(token)).acquire(
                        "https://listen.tidal.com/track/124", tmp_path / "stage"
                    )
        killpg.assert_called_once_with(654, signal.SIGTERM)
    assert list((tmp_path / "stage" / "tidal").glob("*.partial")) == []


@pytest.mark.parametrize("names", [[], ["one.flac", "two.m4a"], ["one.exe"]])
async def test_acquire_requires_exactly_one_valid_audio(tmp_path: Path, names: list[str]) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)

    async def spawn(*args: object, **kwargs: object) -> MagicMock:
        output = Path(args[args.index("--output") + 1])
        for name in names:
            (output / name).write_bytes(b"audio")
        p = MagicMock(pid=1, returncode=0)
        p.communicate = AsyncMock(return_value=(b"", b""))
        return p

    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value="tidal-dl"),
        patch("app.sources.tidal.asyncio.create_subprocess_exec", side_effect=spawn),
        patch("app.sources.tidal._is_supported_audio", return_value=True),
        pytest.raises(ProviderError) as caught,
    ):
        await TidalAdapter(str(config), str(token)).acquire(
            "https://listen.tidal.com/track/123", tmp_path / "stage"
        )
    assert caught.value.code == "artifact_invalid"


async def test_acquire_rejects_symlinked_staging_ancestor(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value="tidal-dl"),
        patch("app.sources.tidal.asyncio.create_subprocess_exec") as spawn,
        pytest.raises(ProviderError) as caught,
    ):
        await TidalAdapter(str(config), str(token)).acquire(
            "https://listen.tidal.com/track/123", linked / "stage"
        )
    assert caught.value.code == "unsafe_staging"
    spawn.assert_not_called()
    assert list(outside.iterdir()) == []


async def test_health_rejects_missing_tidal_dl_executable(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value=""),
    ):
        state = await TidalAdapter(str(config), str(token), "HiFi").health()
    assert state.available is False
    assert state.extra["code"] == "tidal_dl_missing"


async def test_health_rejects_incomplete_and_expired_sessions(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    token.write_bytes(base64.b64encode(json.dumps({"accessToken": "secret"}).encode()))
    incomplete = await TidalAdapter(str(config), str(token)).health()
    assert incomplete.available is False
    assert incomplete.extra["code"] == "session_invalid"

    expired_payload = {
        "userid": "123",
        "countryCode": "US",
        "accessToken": "secret",
        "refreshToken": "refresh-secret",
        "expiresAfter": time.time() - 1,
    }
    token.write_bytes(base64.b64encode(json.dumps(expired_payload).encode()))
    expired = await TidalAdapter(str(config), str(token)).health()
    assert expired.available is False
    assert expired.extra["code"] == "session_expired"


async def test_acquire_classifies_real_stdout_error(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path)
    process = MagicMock(pid=1, returncode=42)
    process.communicate = AsyncMock(return_value=(b"Please login token=secret", b""))
    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value="tidal-dl"),
        patch("app.sources.tidal.asyncio.create_subprocess_exec", return_value=process),
        pytest.raises(ProviderError) as caught,
    ):
        await TidalAdapter(str(config), str(token)).acquire(
            "https://listen.tidal.com/track/123", tmp_path / "stage"
        )
    assert caught.value.code == "auth_required"
    assert "secret" not in caught.value.message


async def test_acquire_cleans_profile_when_snapshot_fails(tmp_path: Path) -> None:
    from app.sources.tidal import TidalAdapter

    config, token = _profile(tmp_path / "home")
    staging = tmp_path / "stage"
    with (
        patch("app.sources.tidal._tidal_dl_version", return_value="2022.10.31.1"),
        patch("app.sources.tidal._tidal_dl_executable", return_value="tidal-dl"),
        patch("app.sources.tidal._snapshot", side_effect=OSError("synthetic")),
        pytest.raises(OSError),
    ):
        await TidalAdapter(str(config), str(token)).acquire(
            "https://tidal.com/browse/track/123", staging
        )
    tidal_stage = staging / "tidal"
    leftovers = await asyncio.to_thread(lambda: list(tidal_stage.iterdir()))
    assert leftovers == []
