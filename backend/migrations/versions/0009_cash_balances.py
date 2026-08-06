"""Create cash balance records.

Revision ID: 0009_cash_balances
Revises: 0008_deposits
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_cash_balances"
down_revision = "0008_deposits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cash_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RUB'"), nullable=False),
        sa.Column("include_in_capital", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("amount_kopecks >= 0", name="ck_cash_balances_amount_nonnegative"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("cash_balances")
