from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def test_0002_migration_defines_release_import_state_tables() -> None:
    migration = Path("alembic/versions/0002_v011_release_import_state.py")

    text = migration.read_text(encoding="utf-8")

    for table in ("releases", "release_candidates", "import_plans", "monitoring_records"):
        assert f'"{table}"' in text

    for state in (
        "queued",
        "searching",
        "acquiring",
        "downloaded",
        "discovered",
        "needs_review",
        "rolled_back",
        "auto_selected",
        "manual_selected",
    ):
        assert f'"{state}"' in text


def test_0002_migration_upgrades_and_downgrades_sqlite(tmp_path: Path) -> None:
    os.environ.setdefault("SECRET_KEY", "test-secret")
    db_path = tmp_path / "migration.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO jobs (source, query, status) VALUES ('youtube', 'q', 'pending')")
        job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
        try:
            conn.execute(
                "INSERT INTO releases (job_id, source, import_state) "
                "VALUES (?, 'youtube', 'bogus')",
                (job_id,),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("invalid release import_state bypassed SQLite constraint")

    command.downgrade(cfg, "base")
