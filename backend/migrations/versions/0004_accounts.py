"""Create account records.

Revision ID: 0004_accounts
Revises: 0003_reporting_months
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_accounts"
down_revision = "0003_reporting_months"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("external_code", sa.String(length=128), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("include_in_capital", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("include_in_returns", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "account_type IN ('brokerage', 'iis', 'deposit', 'savings', 'cash', 'other')",
            name="ck_accounts_account_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'frozen', 'closed', 'hidden')",
            name="ck_accounts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_code", name="uq_accounts_external_code"),
    )


def downgrade() -> None:
    op.drop_table("accounts")
