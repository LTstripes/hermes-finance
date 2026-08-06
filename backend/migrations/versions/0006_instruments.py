"""Create instrument records.

Revision ID: 0006_instruments
Revises: 0005_iis
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_instruments"
down_revision = "0005_iis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("instrument_type", sa.String(length=16), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("moex_secid", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RUB'"), nullable=False),
        sa.Column("nominal_value_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "manual_price_allowed", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "instrument_type IN ('stock', 'bond', 'fund', 'currency', 'gold', 'other')",
            name="ck_instruments_instrument_type",
        ),
        sa.CheckConstraint(
            "nominal_value_kopecks IS NULL OR nominal_value_kopecks >= 0",
            name="ck_instruments_nominal_value_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", name="uq_instruments_isin"),
    )


def downgrade() -> None:
    op.drop_table("instruments")
