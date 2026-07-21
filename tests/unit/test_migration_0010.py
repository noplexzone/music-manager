from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def _cfg(db_path: Path) -> Config:
    os.environ.setdefault("SECRET_KEY", "test-secret")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_0010_catalog_entities_fresh_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh_0010.db"
    cfg = _cfg(db_path)

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"catalog_artists", "catalog_albums", "catalog_album_tracks"}.issubset(tables)
        assert {"catalog_album_id", "catalog_track_id"}.issubset(_columns(conn, "jobs"))
        assert {"catalog_album_id", "catalog_track_id"}.issubset(_columns(conn, "tracks"))

    command.downgrade(cfg, "0009")

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "catalog_artists" not in tables
        assert "catalog_album_id" not in _columns(conn, "jobs")
        assert "catalog_track_id" not in _columns(conn, "tracks")


def test_0010_catalog_entities_existing_db_upgrade_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "existing_0010.db"
    cfg = _cfg(db_path)
    command.upgrade(cfg, "0009")

    command.upgrade(cfg, "0010")
    command.upgrade(cfg, "0010")

    with sqlite3.connect(db_path) as conn:
        assert "name" in _columns(conn, "catalog_artists")
        assert "artist_id" in _columns(conn, "catalog_albums")
        assert "recording_mbid" in _columns(conn, "catalog_album_tracks")
        assert {"catalog_album_id", "catalog_track_id"}.issubset(_columns(conn, "jobs"))
        assert {"catalog_album_id", "catalog_track_id"}.issubset(_columns(conn, "tracks"))
