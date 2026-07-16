"""v0.1.1 release, staging, import, and monitoring state

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    acquisition_state = sa.Enum(
        "queued",
        "searching",
        "acquiring",
        "downloaded",
        "failed",
        "cancelled",
        name="acquisitionstate",
        native_enum=False,
        create_constraint=True,
    )
    import_state = sa.Enum(
        "discovered",
        "staged",
        "matching",
        "needs_review",
        "ready",
        "importing",
        "imported",
        "failed",
        "rolled_back",
        name="importworkflowstate",
        native_enum=False,
        create_constraint=True,
    )
    collision_state = sa.Enum(
        "unchecked",
        "clear",
        "duplicate",
        "conflict",
        "needs_review",
        name="collisionstate",
        native_enum=False,
        create_constraint=True,
    )
    tag_state = sa.Enum(
        "pending",
        "verified",
        "failed",
        "skipped",
        name="tagverificationstate",
        native_enum=False,
        create_constraint=True,
    )
    match_review_state = sa.Enum(
        "pending",
        "auto_selected",
        "needs_review",
        "manual_selected",
        "rejected",
        name="matchreviewstate",
        native_enum=False,
        create_constraint=True,
    )
    monitoring_state = sa.Enum(
        "active",
        "paused",
        "checking",
        "candidate_found",
        "failed",
        name="monitoringstatus",
        native_enum=False,
        create_constraint=True,
    )

    op.create_table(
        "releases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("album_artist", sa.Text, nullable=True),
        sa.Column("year", sa.String(4), nullable=True),
        sa.Column("release_mbid", sa.String(36), nullable=True),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("catalog_number", sa.String(128), nullable=True),
        sa.Column("barcode", sa.String(64), nullable=True),
        sa.Column("track_count", sa.Integer, nullable=True),
        sa.Column("staging_path", sa.Text, nullable=True),
        sa.Column("import_state", import_state, nullable=False, server_default="discovered"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("rollback_detail", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    with op.batch_alter_table("tracks") as batch_op:
        batch_op.add_column(sa.Column("release_id", sa.Integer, nullable=True))
        batch_op.add_column(
            sa.Column(
                "acquisition_state", acquisition_state, nullable=False, server_default="queued"
            )
        )
        batch_op.add_column(
            sa.Column("import_state", import_state, nullable=False, server_default="discovered")
        )
        batch_op.add_column(sa.Column("staging_path", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("content_sha256", sa.String(64), nullable=True))
        batch_op.create_foreign_key(
            "fk_tracks_release_id_releases",
            "releases",
            ["release_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "release_candidates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "release_id",
            sa.Integer,
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "track_id", sa.Integer, sa.ForeignKey("tracks.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("recording_mbid", sa.String(36), nullable=True),
        sa.Column("release_mbid", sa.String(36), nullable=True),
        sa.Column("medium_position", sa.Integer, nullable=True),
        sa.Column("track_position", sa.Integer, nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("track_count", sa.Integer, nullable=True),
        sa.Column("year", sa.String(4), nullable=True),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("catalog_number", sa.String(128), nullable=True),
        sa.Column("barcode", sa.String(64), nullable=True),
        sa.Column("quality_json", sa.Text, nullable=True),
        sa.Column("evidence_json", sa.Text, nullable=True),
        sa.Column("match_score", sa.Float, nullable=True),
        sa.Column("match_reasons_json", sa.Text, nullable=True),
        sa.Column("review_state", match_review_state, nullable=False, server_default="pending"),
        sa.Column("review_audit_json", sa.Text, nullable=True),
        sa.Column("selected", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "import_plans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "release_id",
            sa.Integer,
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "track_id", sa.Integer, sa.ForeignKey("tracks.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("staging_path", sa.Text, nullable=True),
        sa.Column("destination_path", sa.Text, nullable=False),
        sa.Column("destination_temp_path", sa.Text, nullable=True),
        sa.Column("planned_operations_json", sa.Text, nullable=True),
        sa.Column("collision_state", collision_state, nullable=False, server_default="unchecked"),
        sa.Column("tag_verification_state", tag_state, nullable=False, server_default="pending"),
        sa.Column("status", import_state, nullable=False, server_default="discovered"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("rollback_detail", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "monitoring_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "release_id",
            sa.Integer,
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("release_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", monitoring_state, nullable=False, server_default="active"),
        sa.Column("desired_quality_json", sa.Text, nullable=True),
        sa.Column("history_json", sa.Text, nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("monitoring_records")
    op.drop_table("import_plans")
    op.drop_table("release_candidates")
    with op.batch_alter_table("tracks") as batch_op:
        batch_op.drop_constraint("fk_tracks_release_id_releases", type_="foreignkey")
        batch_op.drop_constraint("importworkflowstate", type_="check")
        batch_op.drop_constraint("acquisitionstate", type_="check")
        batch_op.drop_column("content_sha256")
        batch_op.drop_column("staging_path")
        batch_op.drop_column("import_state")
        batch_op.drop_column("acquisition_state")
        batch_op.drop_column("release_id")
    op.drop_table("releases")
