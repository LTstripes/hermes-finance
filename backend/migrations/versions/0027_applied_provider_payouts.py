"""Add applied provider payout, revision, and reconciliation tables.

Revision ID: 0027_applied_provider_payouts
Revises: 0026_t_invest_price_source_and_provenance

Additive R05-04 persistence only. Existing owner tables are not rewritten
and no provider/network call is performed during upgrade or downgrade.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_applied_provider_payouts"
down_revision = "0026_t_invest_price_source_and_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applied_provider_payouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("source_position_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_instrument_uid", sa.String(length=128), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("identity_key", sa.String(length=128), nullable=False),
        sa.Column(
            "lifecycle", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("per_unit_amount", sa.String(length=64), nullable=False),
        sa.Column("total_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RUB'"), nullable=False),
        sa.Column(
            "amount_basis",
            sa.String(length=32),
            server_default=sa.text("'provider_announced'"),
            nullable=False,
        ),
        sa.Column("is_approximate", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("first_applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_kind IN ('coupon', 'dividend', 'redemption')",
            name="ck_applied_provider_payouts_event_kind",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('active', 'cancelled', 'dismissed')",
            name="ck_applied_provider_payouts_lifecycle",
        ),
        sa.CheckConstraint("currency = 'RUB'", name="ck_applied_provider_payouts_currency_rub"),
        sa.CheckConstraint(
            "amount_basis IN ('provider_announced')",
            name="ck_applied_provider_payouts_amount_basis",
        ),
        sa.CheckConstraint(
            "quantity >= 0", name="ck_applied_provider_payouts_quantity_nonnegative"
        ),
        sa.CheckConstraint(
            "total_amount_kopecks >= 0",
            name="ck_applied_provider_payouts_total_nonnegative",
        ),
        sa.CheckConstraint(
            "length(per_unit_amount) > 0",
            name="ck_applied_provider_payouts_per_unit_present",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_position_snapshot_id"],
            ["position_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "provider",
            "provider_instrument_uid",
            "event_kind",
            "identity_key",
            name="uq_applied_provider_payouts_identity",
        ),
    )
    op.create_index(
        "ix_applied_provider_payouts_month",
        "applied_provider_payouts",
        ["reporting_month_id"],
    )

    op.create_table(
        "applied_payout_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("applied_payout_id", sa.Integer(), nullable=False),
        sa.Column("revision_kind", sa.String(length=16), nullable=False),
        sa.Column("source_position_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_instrument_uid", sa.String(length=128), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("identity_key", sa.String(length=128), nullable=False),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("per_unit_amount", sa.String(length=64), nullable=False),
        sa.Column("total_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_basis", sa.String(length=32), nullable=False),
        sa.Column("is_approximate", sa.Boolean(), nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_kind IN ('apply', 'revise', 'cancel', 'dismiss')",
            name="ck_applied_payout_revisions_kind",
        ),
        sa.CheckConstraint(
            "event_kind IN ('coupon', 'dividend', 'redemption')",
            name="ck_applied_payout_revisions_event_kind",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('active', 'cancelled', 'dismissed')",
            name="ck_applied_payout_revisions_lifecycle",
        ),
        sa.CheckConstraint("currency = 'RUB'", name="ck_applied_payout_revisions_currency_rub"),
        sa.CheckConstraint(
            "amount_basis IN ('provider_announced')",
            name="ck_applied_payout_revisions_amount_basis",
        ),
        sa.CheckConstraint(
            "quantity >= 0", name="ck_applied_payout_revisions_quantity_nonnegative"
        ),
        sa.CheckConstraint(
            "total_amount_kopecks >= 0",
            name="ck_applied_payout_revisions_total_nonnegative",
        ),
        sa.CheckConstraint(
            "length(per_unit_amount) > 0",
            name="ck_applied_payout_revisions_per_unit_present",
        ),
        sa.ForeignKeyConstraint(
            ["applied_payout_id"],
            ["applied_provider_payouts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_position_snapshot_id"],
            ["position_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_applied_payout_revisions_payout_id",
        "applied_payout_revisions",
        ["applied_payout_id"],
    )

    op.create_table(
        "applied_payout_reconciliations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("applied_payout_id", sa.Integer(), nullable=False),
        sa.Column("expected_cash_flow_id", sa.Integer(), nullable=False),
        sa.Column("counting_decision", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "counting_decision IN ('keep_both', 'count_manual', 'count_provider')",
            name="ck_applied_payout_reconciliations_decision",
        ),
        sa.ForeignKeyConstraint(
            ["applied_payout_id"],
            ["applied_provider_payouts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["expected_cash_flow_id"],
            ["expected_cash_flows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "applied_payout_id",
            name="uq_applied_payout_reconciliations_payout",
        ),
        sa.UniqueConstraint(
            "expected_cash_flow_id",
            name="uq_applied_payout_reconciliations_manual_flow",
        ),
    )


def downgrade() -> None:
    op.drop_table("applied_payout_reconciliations")
    op.drop_index(
        "ix_applied_payout_revisions_payout_id",
        table_name="applied_payout_revisions",
    )
    op.drop_table("applied_payout_revisions")
    op.drop_index(
        "ix_applied_provider_payouts_month",
        table_name="applied_provider_payouts",
    )
    op.drop_table("applied_provider_payouts")
