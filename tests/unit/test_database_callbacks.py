from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import register_transaction_callbacks


async def test_rollback_callbacks_continue_and_log_individual_failures(
    db_session: AsyncSession, caplog
) -> None:
    await db_session.execute(text("SELECT 1"))
    calls: list[str] = []

    def fails() -> None:
        calls.append("fails")
        raise OSError("forced callback failure")

    def succeeds() -> None:
        calls.append("succeeds")

    register_transaction_callbacks(db_session, after_commit=lambda: None, after_rollback=succeeds)
    register_transaction_callbacks(db_session, after_commit=lambda: None, after_rollback=fails)

    with caplog.at_level(logging.ERROR):
        await db_session.rollback()

    assert calls == ["fails", "succeeds"]
    assert "forced callback failure" in caplog.text
