"""add file_format and file_size_bytes to tracks

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    existing = _columns("tracks")
    with op.batch_alter_table("tracks") as batch_op:
        if "file_format" not in existing:
            batch_op.add_column(sa.Column("file_format", sa.String(16), nullable=True))
        if "file_size_bytes" not in existing:
            batch_op.add_column(sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
        if "file_metadata_checked_at" not in existing:
            batch_op.add_column(
                sa.Column("file_metadata_checked_at", sa.DateTime(timezone=True), nullable=True)
            )


def downgrade() -> None:
    existing = _columns("tracks")
    with op.batch_alter_table("tracks") as batch_op:
        if "file_metadata_checked_at" in existing:
            batch_op.drop_column("file_metadata_checked_at")
        if "file_size_bytes" in existing:
            batch_op.drop_column("file_size_bytes")
        if "file_format" in existing:
            batch_op.drop_column("file_format")
