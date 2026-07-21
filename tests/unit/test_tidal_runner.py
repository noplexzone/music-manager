from __future__ import annotations

import sys
from pathlib import Path

import tidal_dl

from app.sources import tidal_runner


def _patch_runtime(monkeypatch: object, *, login: bool, errors: bool = False) -> list[str]:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    calls: list[str] = []
    monkeypatch.setattr(tidal_dl.SETTINGS, "read", lambda path: calls.append(f"settings:{path}"))
    monkeypatch.setattr(tidal_dl.TOKEN, "read", lambda path: calls.append(f"token:{path}"))
    monkeypatch.setattr(tidal_dl.apiKey, "getItem", lambda index: object())
    monkeypatch.setattr(tidal_dl, "loginByConfig", lambda: login)

    def start(url: str) -> None:
        calls.append(f"start:{url}")
        assert tidal_dl.SETTINGS.albumFolderFormat == "{AlbumID}"
        assert tidal_dl.SETTINGS.playlistFolderFormat == "{PlaylistUUID}"
        assert tidal_dl.SETTINGS.trackFileFormat == "{TrackID}"
        assert tidal_dl.SETTINGS.videoFileFormat == "{VideoID}"
        assert tidal_dl.SETTINGS.usePlaylistFolder is False
        assert tidal_dl.SETTINGS.saveCovers is False
        assert tidal_dl.SETTINGS.saveAlbumInfo is False
        assert tidal_dl.SETTINGS.lyricFile is False
        if errors:
            tidal_dl.Printf.err("download failed")

    monkeypatch.setattr(tidal_dl, "start", start)
    return calls


def test_runner_never_enters_interactive_login(monkeypatch: object, tmp_path: Path) -> None:
    calls = _patch_runtime(monkeypatch, login=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tidal-runner",
            "--url",
            "https://tidal.com/browse/track/123",
            "--output",
            str(tmp_path),
            "--quality",
            "HiFi",
        ],
    )
    assert tidal_runner.main() == 41
    assert not any(call.startswith("start:") for call in calls)


def test_runner_reports_library_errors(monkeypatch: object, tmp_path: Path) -> None:
    calls = _patch_runtime(monkeypatch, login=True, errors=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tidal-runner",
            "--url",
            "https://tidal.com/browse/track/123",
            "--output",
            str(tmp_path),
            "--quality",
            "HiFi",
        ],
    )
    assert tidal_runner.main() == 42
    assert calls[-1] == "start:https://tidal.com/browse/track/123"


def test_runner_success(monkeypatch: object, tmp_path: Path) -> None:
    calls = _patch_runtime(monkeypatch, login=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tidal-runner",
            "--url",
            "https://listen.tidal.com/track/456",
            "--output",
            str(tmp_path),
            "--quality",
            "Master",
        ],
    )
    assert tidal_runner.main() == 0
    assert calls[-1] == "start:https://listen.tidal.com/track/456"
