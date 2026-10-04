"""Explicit class no-crossing coverage; no inferred legacy assertions.

Revision ID: 0046_class_no_crossing_coverage
Revises: 0045_position_historical_instrument_type
"""

import sqlalchemy as sa
from alembic import op

revision = "0046_class_no_crossing_coverage"
down_revision = "0045_position_historical_instrument_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "class_no_crossing_coverages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_class", sa.String(16), nullable=False),
        sa.Column("covered_from", sa.Date(), nullable=False),
        sa.Column("covered_to", sa.Date(), nullable=False),
        sa.Column("coverage_state", sa.String(16), nullable=False),
        sa.Column("provenance_kind", sa.String(64), nullable=False),
        sa.Column("provenance_reference", sa.String(128), nullable=True),
        sa.Column("material_signature", sa.String(64), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "asset_class IN ('stock', 'bond', 'gold')", name="ck_class_coverage_class"
        ),
        sa.CheckConstraint("covered_to > covered_from", name="ck_class_coverage_interval"),
        sa.CheckConstraint(
            "coverage_state IN ('complete', 'unknown', 'revoked')", name="ck_class_coverage_state"
        ),
        sa.CheckConstraint(
            "provenance_kind = 'owner_attestation'", name="ck_class_coverage_provenance"
        ),
        sa.CheckConstraint("revision > 0", name="ck_class_coverage_revision"),
        sa.CheckConstraint(
            "coverage_state <> 'complete' OR "
            "(material_signature IS NOT NULL AND length(material_signature) = 64)",
            name="ck_class_coverage_material",
        ),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM class_no_crossing_coverages LIMIT 1")).first():
        raise RuntimeError("cannot discard class no-crossing evidence")
    op.drop_table("class_no_crossing_coverages")
