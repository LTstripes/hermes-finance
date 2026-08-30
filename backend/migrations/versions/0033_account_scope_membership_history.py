"""Persist effective-dated performance-scope membership evidence.

Revision ID: 0033_account_scope_membership_history
Revises: 0032_cash_balance_account_link

Existing account flags are present-state configuration and are not backfilled
into historical membership rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_account_scope_membership_history"
down_revision = "0032_cash_balance_account_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_performance_scope_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("include_in_returns", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_account_scope_memberships_effective_range",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_account_scope_memberships_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "account_id",
            "effective_from",
            name="uq_account_scope_memberships_account_effective_from",
        ),
    )


def downgrade() -> None:
    op.drop_table("account_performance_scope_memberships")
