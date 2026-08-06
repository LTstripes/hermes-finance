"""Create investment cash flow records.

Revision ID: 0011_investment_cash_flows
Revises: 0010_income_entries
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_investment_cash_flows"
down_revision = "0010_income_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investment_cash_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("flow_type", sa.String(length=16), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("gross_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("commission_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("net_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RUB'"), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "flow_type IN ('interest', 'coupon', 'dividend', 'redemption', 'deposit', "
            "'withdrawal', 'commission', 'tax', 'realized_profit', 'realized_loss', 'other')",
            name="ck_investment_cash_flows_flow_type",
        ),
        sa.CheckConstraint(
            "gross_amount_kopecks >= 0", name="ck_investment_cash_flows_gross_nonnegative"
        ),
        sa.CheckConstraint(
            "tax_amount_kopecks >= 0", name="ck_investment_cash_flows_tax_nonnegative"
        ),
        sa.CheckConstraint(
            "commission_amount_kopecks >= 0",
            name="ck_investment_cash_flows_commission_nonnegative",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("investment_cash_flows")
