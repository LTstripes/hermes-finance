"""Persist C1 position identity without inferring legacy history.

Revision ID: 0045_position_historical_instrument_type
Revises: 0044_observed_valuation_material_signature
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_position_historical_instrument_type"
down_revision = "0044_observed_valuation_material_signature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A column-level check permits additive SQLite ALTER without rebuilding
    # this heavily referenced table (including archived payout identities).
    op.add_column(
        "position_snapshots",
        sa.Column(
            "historical_instrument_type",
            sa.String(16),
            sa.CheckConstraint(
                "historical_instrument_type IS NULL OR "
                "historical_instrument_type IN ('stock', 'bond', 'fund', 'currency', 'gold')",
                name="ck_position_snapshots_historical_instrument_type",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT 1 FROM position_snapshots WHERE historical_instrument_type IS NOT NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError("cannot downgrade position class identity while evidence exists")
    op.drop_column("position_snapshots", "historical_instrument_type")
