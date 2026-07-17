"""Add provider_settings table for encrypted/plain config storage.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_settings",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value_plain", sa.Text, nullable=True),
        sa.Column("value_encrypted", sa.Text, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("provider_settings")
