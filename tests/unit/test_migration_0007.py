from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def test_0007_migration_upgrades_and_downgrades_sqlite(tmp_path: Path) -> None:
    os.environ.setdefault("SECRET_KEY", "test-secret")
    db_path = tmp_path / "migration_0007.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        col_names = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
        assert "file_format" in col_names
        assert "file_size_bytes" in col_names
        assert "file_metadata_checked_at" in col_names

    command.downgrade(cfg, "0006")

    with sqlite3.connect(db_path) as conn:
        col_names_after = {row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()}
        assert "file_format" not in col_names_after
        assert "file_size_bytes" not in col_names_after
        assert "file_metadata_checked_at" not in col_names_after
