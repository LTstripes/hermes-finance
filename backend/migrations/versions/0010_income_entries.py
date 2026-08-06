"""Create income entry records.

Revision ID: 0010_income_entries
Revises: 0009_cash_balances
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_income_entries"
down_revision = "0009_cash_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "income_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("income_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("gross_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("net_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.Date(), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "include_in_cash_flow", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "include_in_passive_income", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "income_type IN ('salary', 'bonus', 'side_income', 'cashback', 'other')",
            name="ck_income_entries_income_type",
        ),
        sa.CheckConstraint("gross_amount_kopecks >= 0", name="ck_income_entries_gross_nonnegative"),
        sa.CheckConstraint("tax_amount_kopecks >= 0", name="ck_income_entries_tax_nonnegative"),
        sa.CheckConstraint("net_amount_kopecks >= 0", name="ck_income_entries_net_nonnegative"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("income_entries")
