"""Add catalog metadata entities.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_fk_column(table_name: str, column_name: str, target: str) -> None:
    if table_name not in _tables() or column_name in _columns(table_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column(column_name, sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            f"fk_{table_name}_{column_name}", target, [column_name], ["id"], ondelete="SET NULL"
        )


def upgrade() -> None:
    tables = _tables()
    if "catalog_artists" not in tables:
        op.create_table(
            "catalog_artists",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("mbid", sa.String(36), nullable=True),
            sa.Column("deezer_id", sa.String(64), nullable=True),
            sa.Column("itunes_id", sa.String(64), nullable=True),
            sa.Column("artwork_url", sa.Text(), nullable=True),
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
            sa.UniqueConstraint("mbid", name="uq_catalog_artists_mbid"),
            sa.UniqueConstraint("deezer_id", name="uq_catalog_artists_deezer_id"),
            sa.UniqueConstraint("itunes_id", name="uq_catalog_artists_itunes_id"),
        )
    tables = _tables()
    if "catalog_albums" not in tables:
        op.create_table(
            "catalog_albums",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "artist_id",
                sa.Integer(),
                sa.ForeignKey("catalog_artists.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("year", sa.String(4), nullable=True),
            sa.Column("release_type", sa.String(64), nullable=True),
            sa.Column("mbid", sa.String(36), nullable=True),
            sa.Column("deezer_id", sa.String(64), nullable=True),
            sa.Column("itunes_id", sa.String(64), nullable=True),
            sa.Column("artwork_url", sa.Text(), nullable=True),
            sa.Column("track_count", sa.Integer(), nullable=True),
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
            sa.UniqueConstraint("mbid", name="uq_catalog_albums_mbid"),
            sa.UniqueConstraint("deezer_id", name="uq_catalog_albums_deezer_id"),
            sa.UniqueConstraint("itunes_id", name="uq_catalog_albums_itunes_id"),
        )
    tables = _tables()
    if "catalog_album_tracks" not in tables:
        op.create_table(
            "catalog_album_tracks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "album_id",
                sa.Integer(),
                sa.ForeignKey("catalog_albums.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("disc", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("duration_sec", sa.Integer(), nullable=True),
            sa.Column("recording_mbid", sa.String(36), nullable=True),
        )
    _add_fk_column("jobs", "catalog_album_id", "catalog_albums")
    _add_fk_column("jobs", "catalog_track_id", "catalog_album_tracks")
    _add_fk_column("tracks", "catalog_album_id", "catalog_albums")
    _add_fk_column("tracks", "catalog_track_id", "catalog_album_tracks")


def downgrade() -> None:
    for table in ("tracks", "jobs"):
        if table in _tables():
            existing = _columns(table)
            with op.batch_alter_table(table) as batch_op:
                if "catalog_track_id" in existing:
                    batch_op.drop_column("catalog_track_id")
                if "catalog_album_id" in existing:
                    batch_op.drop_column("catalog_album_id")
    for table in ("catalog_album_tracks", "catalog_albums", "catalog_artists"):
        if table in _tables():
            op.drop_table(table)
