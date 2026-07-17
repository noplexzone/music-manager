from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def test_0006_migration_defines_provider_settings_table() -> None:
    migration = Path("alembic/versions/0006_provider_settings.py")
    text = migration.read_text(encoding="utf-8")
    assert '"provider_settings"' in text
    assert "value_plain" in text
    assert "value_encrypted" in text
    assert "updated_at" in text


def test_0006_migration_upgrades_and_downgrades_sqlite(tmp_path: Path) -> None:
    os.environ.setdefault("SECRET_KEY", "test-secret")
    db_path = tmp_path / "migration_0006.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "provider_settings" in tables

        conn.execute(
            "INSERT INTO provider_settings (key, value_plain, updated_at) "
            "VALUES ('slskd_url', 'http://slskd:5030', datetime('now'))"
        )
        row = conn.execute(
            "SELECT value_plain FROM provider_settings WHERE key = 'slskd_url'"
        ).fetchone()
        assert row is not None
        assert row[0] == "http://slskd:5030"

    command.downgrade(cfg, "0005")

    with sqlite3.connect(db_path) as conn:
        tables_after = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "provider_settings" not in tables_after
        assert "app_users" in tables_after
