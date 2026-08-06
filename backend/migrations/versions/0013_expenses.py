"""Create expense entry and saving allocation records.

Revision ID: 0013_expenses
Revises: 0012_expected_cash_flows
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_expenses"
down_revision = "0012_expected_cash_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expense_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("expense_type", sa.String(length=16), nullable=False),
        sa.Column("is_recurring", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "expense_type IN ('mandatory', 'comfortable', 'other')",
            name="ck_expense_entries_expense_type",
        ),
        sa.CheckConstraint("amount_kopecks >= 0", name="ck_expense_entries_amount_nonnegative"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "saving_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("destination", sa.String(length=128), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("amount_kopecks >= 0", name="ck_saving_allocations_amount_nonnegative"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("saving_allocations")
    op.drop_table("expense_entries")
