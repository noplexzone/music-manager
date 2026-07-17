from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
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


def test_alembic_cli_prefers_database_url_environment(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    target_db = tmp_path / "configured.db"
    fallback_db = tmp_path / "fallback.db"
    config_path = tmp_path / "alembic.ini"
    config_text = (repo / "alembic.ini").read_text(encoding="utf-8")
    config_text = config_text.replace(
        "script_location = alembic", f"script_location = {repo / 'alembic'}", 1
    ).replace(
        "sqlalchemy.url = sqlite+aiosqlite:///./data/music_manager.db",
        f"sqlalchemy.url = sqlite+aiosqlite:///{fallback_db}",
        1,
    )
    config_path.write_text(config_text, encoding="utf-8")
    env = os.environ.copy()
    env.update(
        SECRET_KEY="migration-environment-test-secret",
        DATABASE_URL=f"sqlite+aiosqlite:///{target_db}",
    )

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(config_path), "upgrade", "head"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert target_db.exists()
    assert not fallback_db.exists()
    with sqlite3.connect(target_db) as conn:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='app_users'"
        ).fetchone() == (1,)
