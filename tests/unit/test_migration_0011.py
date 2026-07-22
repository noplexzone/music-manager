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


def test_0011_monitoring_fresh_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh_0011.db"
    cfg = _cfg(db_path)

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        artist_cols = _columns(conn, "catalog_artists")
        album_cols = _columns(conn, "catalog_albums")
        assert {
            "monitored",
            "monitor_policy",
            "last_refreshed_at",
            "last_enriched_at",
            "provenance_json",
        }.issubset(artist_cols)
        assert {"monitored", "in_library", "providers_json"}.issubset(album_cols)

    command.downgrade(cfg, "0010")

    with sqlite3.connect(db_path) as conn:
        assert "monitored" not in _columns(conn, "catalog_artists")
        assert "providers_json" not in _columns(conn, "catalog_albums")


def test_0011_monitoring_existing_v030_upgrade_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "existing_0011.db"
    cfg = _cfg(db_path)
    command.upgrade(cfg, "0010")

    command.upgrade(cfg, "0011")
    command.upgrade(cfg, "0011")

    with sqlite3.connect(db_path) as conn:
        assert "monitor_policy" in _columns(conn, "catalog_artists")
        assert "providers_json" in _columns(conn, "catalog_albums")
