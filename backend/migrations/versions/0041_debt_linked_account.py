"""Add the month-local authoritative debt-to-account link.

Revision ID: 0041_debt_linked_account
Revises: 0040_in_kind_boundary_coverage

The nullable link is additive. Existing debt rows remain unlinked; this
migration does not infer relationships from names, balances, or account types.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_debt_linked_account"
down_revision = "0040_in_kind_boundary_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("debts") as batch_op:
        batch_op.add_column(sa.Column("linked_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_debts_linked_account_id_accounts",
            "accounts",
            ["linked_account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_debts_linked_account_eligibility",
            "linked_account_id IS NULL OR "
            "(debt_type = 'credit_card' AND include_in_liquid_capital)",
        )
        batch_op.create_unique_constraint(
            "uq_debts_reporting_month_linked_account",
            ["reporting_month_id", "linked_account_id"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    linked_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM debts WHERE linked_account_id IS NOT NULL")
    ).scalar_one()
    if linked_count:
        raise RuntimeError(
            "cannot downgrade 0041_debt_linked_account while debt-account links exist"
        )

    with op.batch_alter_table("debts") as batch_op:
        batch_op.drop_constraint("uq_debts_reporting_month_linked_account", type_="unique")
        batch_op.drop_constraint("ck_debts_linked_account_eligibility", type_="check")
        batch_op.drop_constraint("fk_debts_linked_account_id_accounts", type_="foreignkey")
        batch_op.drop_column("linked_account_id")
