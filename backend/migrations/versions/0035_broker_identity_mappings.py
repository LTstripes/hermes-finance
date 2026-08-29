"""Add persistent broker identity mapping registry.

Revision ID: 0035_broker_identity_mappings
Revises: 0034_observed_valuation_boundaries

Additive ADR 0016 Slice A persistence only. No backfill from market mappings,
statement imports, names, tickers, IIAType, sections, or historical months.
No quantity/baseline provenance writes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_broker_identity_mappings"
down_revision = "0034_observed_valuation_boundaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_identity_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("provider_identity", sa.String(length=128), nullable=False),
        sa.Column("hermes_account_id", sa.Integer(), nullable=True),
        sa.Column("hermes_instrument_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_isin", sa.String(length=12), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("predecessor_mapping_id", sa.Integer(), nullable=True),
        sa.Column("successor_mapping_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=256), nullable=True),
        sa.CheckConstraint(
            "subject_kind IN ('account', 'instrument')",
            name="ck_broker_identity_mappings_subject_kind",
        ),
        sa.CheckConstraint(
            "status IN ('effective', 'revoked', 'superseded')",
            name="ck_broker_identity_mappings_status",
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_broker_identity_mappings_provider_present",
        ),
        sa.CheckConstraint(
            "length(trim(provider_identity)) > 0",
            name="ck_broker_identity_mappings_identity_present",
        ),
        sa.CheckConstraint(
            "("
            "subject_kind = 'account' "
            "AND hermes_account_id IS NOT NULL "
            "AND hermes_instrument_id IS NULL"
            ") OR ("
            "subject_kind = 'instrument' "
            "AND hermes_instrument_id IS NOT NULL "
            "AND hermes_account_id IS NULL"
            ")",
            name="ck_broker_identity_mappings_target_shape",
        ),
        sa.CheckConstraint(
            "subject_kind = 'instrument' OR observed_isin IS NULL",
            name="ck_broker_identity_mappings_isin_instruments_only",
        ),
        sa.CheckConstraint(
            "("
            "status = 'revoked' AND revoked_at IS NOT NULL"
            ") OR ("
            "status != 'revoked' AND revoked_at IS NULL AND revoke_reason IS NULL"
            ")",
            name="ck_broker_identity_mappings_revoke_clock",
        ),
        sa.CheckConstraint(
            "("
            "status = 'superseded' AND successor_mapping_id IS NOT NULL"
            ") OR ("
            "status != 'superseded'"
            ")",
            name="ck_broker_identity_mappings_superseded_successor",
        ),
        sa.ForeignKeyConstraint(
            ["hermes_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hermes_instrument_id"],
            ["instruments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_mapping_id"],
            ["broker_identity_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["successor_mapping_id"],
            ["broker_identity_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_broker_identity_mappings_provider_status",
        "broker_identity_mappings",
        ["provider", "status"],
    )
    op.create_index(
        "uq_broker_identity_mappings_effective_forward",
        "broker_identity_mappings",
        ["provider", "subject_kind", "provider_identity"],
        unique=True,
        sqlite_where=sa.text("status = 'effective'"),
    )
    op.create_index(
        "uq_broker_identity_mappings_effective_instrument_reverse",
        "broker_identity_mappings",
        ["provider", "hermes_instrument_id"],
        unique=True,
        sqlite_where=sa.text("status = 'effective' AND subject_kind = 'instrument'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_broker_identity_mappings_effective_instrument_reverse",
        table_name="broker_identity_mappings",
    )
    op.drop_index(
        "uq_broker_identity_mappings_effective_forward",
        table_name="broker_identity_mappings",
    )
    op.drop_index(
        "ix_broker_identity_mappings_provider_status",
        table_name="broker_identity_mappings",
    )
    op.drop_table("broker_identity_mappings")
