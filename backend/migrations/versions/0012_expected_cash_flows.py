"""Create expected cash flow forecast records.

Revision ID: 0012_expected_cash_flows
Revises: 0011_investment_cash_flows
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_expected_cash_flows"
down_revision = "0011_investment_cash_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expected_cash_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("flow_type", sa.String(length=16), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=False),
        sa.Column("gross_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("expected_tax_amount_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("expected_net_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RUB'"), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_as_of_date", sa.Date(), nullable=False),
        sa.Column("forecast_version", sa.String(length=32), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_approximate", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "flow_type IN ('coupon', 'dividend', 'interest', 'redemption', 'other')",
            name="ck_expected_cash_flows_flow_type",
        ),
        sa.CheckConstraint(
            "gross_amount_kopecks >= 0", name="ck_expected_cash_flows_gross_nonnegative"
        ),
        sa.CheckConstraint(
            "expected_tax_amount_kopecks IS NULL OR expected_tax_amount_kopecks >= 0",
            name="ck_expected_cash_flows_tax_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_net_amount_kopecks >= 0", name="ck_expected_cash_flows_net_nonnegative"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            "flow_type",
            "expected_date",
            "forecast_version",
            name="uq_expected_cash_flows_snapshot_event",
        ),
    )


def downgrade() -> None:
    op.drop_table("expected_cash_flows")
