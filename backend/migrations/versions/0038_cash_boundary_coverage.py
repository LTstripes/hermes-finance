"""Persist affirmative cash-boundary history coverage.

Revision ID: 0038_cash_boundary_coverage
Revises: 0036_broker_baseline_provenance

The table stores interval completeness evidence only.  It has no amount
columns and the migration deliberately does not backfill existing history.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_cash_boundary_coverage"
down_revision = "0037_336_financial_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cash_boundary_coverages",
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
            name="ck_cash_boundary_coverages_interval",
        ),
        sa.CheckConstraint(
            "coverage_state IN ('complete', 'unknown')",
            name="ck_cash_boundary_coverages_state",
        ),
        sa.CheckConstraint(
            "length(trim(provenance_kind)) > 0",
            name="ck_cash_boundary_coverages_provenance_kind",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "covered_from",
            "covered_to",
            name="uq_cash_boundary_coverages_account_interval",
        ),
    )
    op.create_index(
        "ix_cash_boundary_coverages_account_interval",
        "cash_boundary_coverages",
        ["account_id", "covered_from", "covered_to"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(sa.text("SELECT COUNT(*) FROM cash_boundary_coverages")).scalar_one()
    if count:
        raise RuntimeError(
            "cannot downgrade 0038_cash_boundary_coverage while coverage evidence exists"
        )
    op.drop_index(
        "ix_cash_boundary_coverages_account_interval",
        table_name="cash_boundary_coverages",
    )
    op.drop_table("cash_boundary_coverages")
