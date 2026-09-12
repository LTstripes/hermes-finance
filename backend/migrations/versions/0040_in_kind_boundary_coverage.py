"""Persist explicit in-kind boundary coverage and movement markers.

Revision ID: 0040_in_kind_boundary_coverage
Revises: 0039_transfer_reconciliation_evidence

The migration is additive. It does not backfill coverage or reinterpret
historical position changes as in-kind movements.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_in_kind_boundary_coverage"
down_revision = "0039_transfer_reconciliation_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "in_kind_boundary_coverages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("covered_from", sa.Date(), nullable=False),
        sa.Column("covered_to", sa.Date(), nullable=False),
        sa.Column("coverage_state", sa.String(length=16), nullable=False),
        sa.Column("provenance_kind", sa.String(length=64), nullable=False),
        sa.Column("provenance_reference", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "covered_to >= covered_from",
            name="ck_in_kind_boundary_coverages_interval",
        ),
        sa.CheckConstraint(
            "coverage_state IN ('complete', 'unknown')",
            name="ck_in_kind_boundary_coverages_state",
        ),
        sa.CheckConstraint(
            "length(trim(provenance_kind)) > 0",
            name="ck_in_kind_boundary_coverages_provenance_kind",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "covered_from",
            "covered_to",
            name="uq_in_kind_boundary_coverages_account_interval",
        ),
    )
    op.create_index(
        "ix_in_kind_boundary_coverages_account_interval",
        "in_kind_boundary_coverages",
        ["account_id", "covered_from", "covered_to"],
    )

    op.create_table(
        "in_kind_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("source_account_id", sa.Integer(), nullable=True),
        sa.Column("destination_account_id", sa.Integer(), nullable=True),
        sa.Column("movement_kind", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("provenance_kind", sa.String(length=64), nullable=False),
        sa.Column("provenance_reference", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "movement_kind IN ('external_in', 'external_out', 'internal_transfer')",
            name="ck_in_kind_movements_kind",
        ),
        sa.CheckConstraint(
            "(movement_kind = 'external_in' AND source_account_id IS NULL "
            "AND destination_account_id IS NOT NULL) OR "
            "(movement_kind = 'external_out' AND source_account_id IS NOT NULL "
            "AND destination_account_id IS NULL) OR "
            "(movement_kind = 'internal_transfer' AND source_account_id IS NOT NULL "
            "AND destination_account_id IS NOT NULL "
            "AND source_account_id <> destination_account_id)",
            name="ck_in_kind_movements_account_directions",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_in_kind_movements_quantity_positive",
        ),
        sa.CheckConstraint(
            "length(trim(provenance_kind)) > 0",
            name="ck_in_kind_movements_provenance_kind",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["destination_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_in_kind_movements_event_date",
        "in_kind_movements",
        ["event_date"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    movement_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM in_kind_movements")
    ).scalar_one()
    coverage_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM in_kind_boundary_coverages")
    ).scalar_one()
    if movement_count or coverage_count:
        raise RuntimeError("cannot downgrade 0040_in_kind_boundary_coverage while evidence exists")
    op.drop_index("ix_in_kind_movements_event_date", table_name="in_kind_movements")
    op.drop_table("in_kind_movements")
    op.drop_index(
        "ix_in_kind_boundary_coverages_account_interval",
        table_name="in_kind_boundary_coverages",
    )
    op.drop_table("in_kind_boundary_coverages")
