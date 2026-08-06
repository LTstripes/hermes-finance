"""Create position snapshot records.

Revision ID: 0007_positions
Revises: 0006_instruments
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_positions"
down_revision = "0006_instruments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("average_cost_per_unit_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("market_price_per_unit_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("accrued_interest_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("market_value_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("cost_basis_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("unrealized_result_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column(
            "price_source",
            sa.String(length=16),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("manual_adjustment", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("quantity >= 0", name="ck_position_snapshots_quantity_nonnegative"),
        sa.CheckConstraint(
            "average_cost_per_unit_kopecks >= 0",
            name="ck_position_snapshots_average_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "market_price_per_unit_kopecks >= 0",
            name="ck_position_snapshots_market_price_nonnegative",
        ),
        sa.CheckConstraint(
            "accrued_interest_kopecks IS NULL OR accrued_interest_kopecks >= 0",
            name="ck_position_snapshots_accrued_interest_nonnegative",
        ),
        sa.CheckConstraint(
            "market_value_kopecks >= 0",
            name="ck_position_snapshots_market_value_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_basis_kopecks >= 0",
            name="ck_position_snapshots_cost_basis_nonnegative",
        ),
        sa.CheckConstraint(
            "price_source IN ('manual', 'moex', 'alfa_pdf')",
            name="ck_position_snapshots_price_source",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            name="uq_position_snapshots_month_account_instrument",
        ),
    )


def downgrade() -> None:
    op.drop_table("position_snapshots")
