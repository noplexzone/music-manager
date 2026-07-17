"""add application users and expiring sessions

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column(
            "role", sa.Enum("owner", "admin", "member", "viewer", name="userrole"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_app_users_username", "app_users", ["username"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_app_users_username", table_name="app_users")
    op.drop_table("app_users")
