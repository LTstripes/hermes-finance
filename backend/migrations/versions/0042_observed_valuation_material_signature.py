"""Bind observed valuations to the material state of their flow or group.

Revision ID: 0042_observed_valuation_material_signature
Revises: 0041_debt_linked_account

Existing observations have no provable capture-time material identity. Leave
them unbound so read-time availability fails closed until they are recaptured.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_observed_valuation_material_signature"
down_revision = "0041_debt_linked_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "observed_valuation_points",
        sa.Column("material_signature", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM observed_valuation_points LIMIT 1")).first():
        raise RuntimeError(
            "cannot downgrade observed valuation material binding while evidence exists"
        )
    op.drop_column("observed_valuation_points", "material_signature")
