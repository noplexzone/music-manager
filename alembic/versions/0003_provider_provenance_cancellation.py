"""persist provider provenance and job cancellation

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-16 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_STATUS = sa.Enum("pending", "running", "done", "failed", name="jobstatus")
_NEW_JOB_STATUS = sa.Enum("pending", "running", "done", "failed", "cancelled", name="jobstatus")


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=_OLD_JOB_STATUS, type_=_NEW_JOB_STATUS)
    with op.batch_alter_table("tracks") as batch_op:
        batch_op.add_column(sa.Column("acquisition_provenance_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tracks") as batch_op:
        batch_op.drop_column("acquisition_provenance_json")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("status", existing_type=_NEW_JOB_STATUS, type_=_OLD_JOB_STATUS)
