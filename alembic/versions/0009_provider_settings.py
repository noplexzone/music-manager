"""Add provider_settings table for encrypted/plain config storage.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    tables = _tables()
    if "tracks" in tables:
        track_columns = _columns("tracks")
        if "file_metadata_checked_at" not in track_columns:
            with op.batch_alter_table("tracks") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "file_metadata_checked_at",
                        sa.DateTime(timezone=True),
                        nullable=True,
                    )
                )

    if "provider_settings" not in tables:
        op.create_table(
            "provider_settings",
            sa.Column("key", sa.String(128), nullable=False),
            sa.Column("value_plain", sa.Text(), nullable=True),
            sa.Column("value_encrypted", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    if "provider_settings" in _tables():
        op.drop_table("provider_settings")
