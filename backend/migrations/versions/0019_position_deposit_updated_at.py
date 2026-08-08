"""Add updated_at to position_snapshots and deposit_snapshots (D05).

Adds an ``updated_at`` DATETIME column (NOT NULL, server-default
``CURRENT_TIMESTAMP``) to both snapshot tables so the API layer can
implement optimistic concurrency via ``If-Match``.

SQLite does not support adding a NOT NULL column without a default, so
``batch_alter_table`` is used to recreate the tables with the new column
and copy existing data. The ORM ``onupdate`` lambda keeps the value fresh
on writes; the server default fills existing rows and any rows inserted
outside the ORM.

Revision ID: 0019_position_deposit_updated_at
Revises: 0018_tax_brackets
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_position_deposit_updated_at"
down_revision = "0018_tax_brackets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("position_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    with op.batch_alter_table("deposit_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("deposit_snapshots") as batch_op:
        batch_op.drop_column("updated_at")

    with op.batch_alter_table("position_snapshots") as batch_op:
        batch_op.drop_column("updated_at")
