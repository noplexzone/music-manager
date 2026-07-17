"""Enforce a single first-run owner account.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_app_users_single_owner",
        "app_users",
        ["role"],
        unique=True,
        sqlite_where=sa.text("role = 'owner'"),
        postgresql_where=sa.text("role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_index("uq_app_users_single_owner", table_name="app_users")
