"""Initial schema: jobs, tracks, path_previews

Revision ID: 0001
Revises:
Create Date: 2026-07-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="jobstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("result_json", sa.Text, nullable=True),
    )

    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("artist", sa.Text, nullable=True),
        sa.Column("album_artist", sa.Text, nullable=True),
        sa.Column("album", sa.Text, nullable=True),
        sa.Column("year", sa.String(4), nullable=True),
        sa.Column("disc", sa.Integer, nullable=True),
        sa.Column("disc_total", sa.Integer, nullable=True),
        sa.Column("track_no", sa.Integer, nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("mbid", sa.String(36), nullable=True),
        sa.Column(
            "identity_state",
            sa.Enum("pending", "resolved", "unresolved", name="identityresolutionstate"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("acoustid", sa.Text, nullable=True),
        sa.Column("deezer_id", sa.String(32), nullable=True),
        sa.Column("source_path", sa.Text, nullable=True),
        sa.Column("source_job_id", sa.String(128), nullable=True),
        sa.Column("source_status", sa.String(128), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "fingerprint_state",
            sa.Enum("pending", "done", "failed", "skipped", name="fingerprintstate"),
            nullable=False,
            server_default="pending",
        ),
    )

    op.create_table(
        "path_previews",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "track_id",
            sa.Integer,
            sa.ForeignKey("tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rendered_path", sa.Text, nullable=False),
        sa.Column("naming_template", sa.Text, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("path_previews")
    op.drop_table("tracks")
    op.drop_table("jobs")
