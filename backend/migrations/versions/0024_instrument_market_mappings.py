"""Add explicit instrument market-data mapping storage.

Revision ID: 0024_instrument_market_mappings
Revises: 0023_passive_income_history_eligibility

Creates an empty 1:1 mapping table. Existing ``instruments.moex_secid`` values
are left untouched and are not inferred as an accepted board-aware mapping.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_instrument_market_mappings"
down_revision = "0023_passive_income_history_eligibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_market_mappings",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("engine", sa.String(length=32), nullable=True),
        sa.Column("market", sa.String(length=32), nullable=True),
        sa.Column("boardid", sa.String(length=32), nullable=True),
        sa.Column("secid", sa.String(length=32), nullable=True),
        sa.Column("excluded", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "("
            "(provider IS NULL AND engine IS NULL AND market IS NULL "
            "AND boardid IS NULL AND secid IS NULL) "
            "OR "
            "(provider IS NOT NULL AND engine IS NOT NULL AND market IS NOT NULL "
            "AND boardid IS NOT NULL AND secid IS NOT NULL)"
            ")",
            name="ck_instrument_market_mappings_identity_atomic",
        ),
        sa.CheckConstraint(
            "excluded = 1 OR ("
            "provider IS NOT NULL AND engine IS NOT NULL AND market IS NOT NULL "
            "AND boardid IS NOT NULL AND secid IS NOT NULL"
            ")",
            name="ck_instrument_market_mappings_mapped_complete",
        ),
        sa.CheckConstraint(
            "excluded IN (0, 1)",
            name="ck_instrument_market_mappings_excluded_bool",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_instrument_market_mappings_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instrument_id"),
    )


def downgrade() -> None:
    op.drop_table("instrument_market_mappings")
