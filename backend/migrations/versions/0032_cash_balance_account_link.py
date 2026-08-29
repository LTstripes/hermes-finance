"""Add optional account identity for performance-scope cash coverage.

Revision ID: 0032_cash_balance_account_link
Revises: 0031_external_flow_scope_membership

Existing cash rows remain NULL and therefore unclassified for performance.
The migration performs no backfill or name-based account inference.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_cash_balance_account_link"
down_revision = "0031_external_flow_scope_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cash_balances") as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_cash_balances_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("cash_balances") as batch_op:
        batch_op.drop_constraint("fk_cash_balances_account_id_accounts", type_="foreignkey")
        batch_op.drop_column("account_id")
