"""monitoring and enrichment fields

Revision ID: 0011
Revises: 0010_catalog_entities
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    artist_cols = _cols("catalog_artists")
    album_cols = _cols("catalog_albums")
    with op.batch_alter_table("catalog_artists") as batch:
        if "provenance_json" not in artist_cols:
            batch.add_column(sa.Column("provenance_json", sa.Text(), nullable=True))
        if "monitored" not in artist_cols:
            batch.add_column(
                sa.Column("monitored", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "monitor_policy" not in artist_cols:
            batch.add_column(
                sa.Column(
                    "monitor_policy", sa.String(length=32), nullable=False, server_default="all"
                )
            )
        if "last_enriched_at" not in artist_cols:
            batch.add_column(
                sa.Column("last_enriched_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "last_refreshed_at" not in artist_cols:
            batch.add_column(
                sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True)
            )
    with op.batch_alter_table("catalog_albums") as batch:
        if "providers_json" not in album_cols:
            batch.add_column(sa.Column("providers_json", sa.Text(), nullable=True))
        if "provenance_json" not in album_cols:
            batch.add_column(sa.Column("provenance_json", sa.Text(), nullable=True))
        if "monitored" not in album_cols:
            batch.add_column(
                sa.Column("monitored", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "in_library" not in album_cols:
            batch.add_column(
                sa.Column("in_library", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    with op.batch_alter_table("catalog_albums") as batch:
        for name in ["in_library", "monitored", "provenance_json", "providers_json"]:
            batch.drop_column(name)
    with op.batch_alter_table("catalog_artists") as batch:
        for name in [
            "last_refreshed_at",
            "last_enriched_at",
            "monitor_policy",
            "monitored",
            "provenance_json",
        ]:
            batch.drop_column(name)
