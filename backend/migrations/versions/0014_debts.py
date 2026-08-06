"""Create debt records.

Revision ID: 0014_debts
Revises: 0013_expenses
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_debts"
down_revision = "0013_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "debts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("debt_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("current_balance_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "include_in_liquid_capital", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("debt_type IN ('credit_card', 'other')", name="ck_debts_debt_type"),
        sa.CheckConstraint(
            "current_balance_kopecks >= 0", name="ck_debts_current_balance_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("debts")
