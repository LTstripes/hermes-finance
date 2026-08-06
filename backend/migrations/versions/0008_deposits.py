"""Create deposit snapshot records.

Revision ID: 0008_deposits
Revises: 0007_positions
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_deposits"
down_revision = "0007_positions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deposit_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("deposit_type", sa.String(length=16), nullable=False),
        sa.Column("balance_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("annual_rate_basis_points", sa.Integer(), nullable=False),
        sa.Column("expected_monthly_interest_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "actual_interest_received_kopecks",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "deposit_type IN ('deposit', 'savings')",
            name="ck_deposit_snapshots_deposit_type",
        ),
        sa.CheckConstraint("balance_kopecks >= 0", name="ck_deposit_snapshots_balance_nonnegative"),
        sa.CheckConstraint(
            "annual_rate_basis_points >= 0",
            name="ck_deposit_snapshots_annual_rate_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_monthly_interest_kopecks >= 0",
            name="ck_deposit_snapshots_expected_interest_nonnegative",
        ),
        sa.CheckConstraint(
            "actual_interest_received_kopecks >= 0",
            name="ck_deposit_snapshots_actual_interest_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("deposit_snapshots")
