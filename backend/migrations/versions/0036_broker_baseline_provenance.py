"""Add owner-approved Alfa baseline provenance.

Revision ID: 0036_broker_baseline_provenance
Revises: 0035_broker_identity_mappings

Additive ADR 0016 Slice B persistence only. No backfill, no cash/price/NKD/P&L
columns, no raw payloads, no T-Invest broker import.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_broker_baseline_provenance"
down_revision = "0035_broker_identity_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_baseline_applies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("baseline_date", sa.Date(), nullable=False),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compatibility_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("apply_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_broker_baseline_applies_provider_present",
        ),
        sa.CheckConstraint(
            "length(trim(apply_fingerprint)) > 0",
            name="ck_broker_baseline_applies_fingerprint_present",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_broker_baseline_applies_month_confirmed",
        "broker_baseline_applies",
        ["reporting_month_id", "confirmed_at"],
    )
    op.create_table(
        "broker_baseline_apply_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("baseline_apply_id", sa.Integer(), nullable=False),
        sa.Column("position_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'unchanged')",
            name="ck_broker_baseline_apply_items_action",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_broker_baseline_apply_items_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_apply_id"],
            ["broker_baseline_applies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["position_snapshot_id"],
            ["position_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_broker_baseline_apply_items_apply_id",
        "broker_baseline_apply_items",
        ["baseline_apply_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_broker_baseline_apply_items_apply_id",
        table_name="broker_baseline_apply_items",
    )
    op.drop_table("broker_baseline_apply_items")
    op.drop_index(
        "ix_broker_baseline_applies_month_confirmed",
        table_name="broker_baseline_applies",
    )
    op.drop_table("broker_baseline_applies")
