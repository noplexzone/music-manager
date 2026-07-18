"""add file_format and file_size_bytes to tracks

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-17

"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tracks") as batch_op:
        batch_op.add_column(sa.Column("file_format", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("file_metadata_checked_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tracks") as batch_op:
        batch_op.drop_column("file_metadata_checked_at")
        batch_op.drop_column("file_size_bytes")
        batch_op.drop_column("file_format")
