"""Explicit whole-class endpoint inventory claims; legacy evidence stays unknown.

Revision ID: 0047_class_endpoint_inventory
Revises: 0046_class_no_crossing_coverage
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_class_endpoint_inventory"
down_revision = "0046_class_no_crossing_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("opening_inventory_complete", "closing_inventory_complete"):
        op.add_column(
            "class_no_crossing_coverages",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM class_no_crossing_coverages "
                "WHERE opening_inventory_complete OR closing_inventory_complete LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("cannot discard class endpoint inventory evidence")
    with op.batch_alter_table("class_no_crossing_coverages") as batch_op:
        batch_op.drop_column("closing_inventory_complete")
        batch_op.drop_column("opening_inventory_complete")
