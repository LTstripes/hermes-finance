"""Create IIS profiles, contributions and tax benefits.

Revision ID: 0005_iis
Revises: 0004_accounts
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_iis"
down_revision = "0004_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "iis_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("iis_type", sa.String(length=32), nullable=False),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column("eligible_close_at", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_iis_profiles_account_id"),
    )
    op.create_table(
        "iis_contributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("is_target_reached", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("tax_year BETWEEN 1900 AND 9999", name="ck_iis_contributions_tax_year"),
        sa.CheckConstraint("amount_kopecks >= 0", name="ck_iis_contributions_amount_nonnegative"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "tax_year", name="uq_iis_contributions_account_year"),
    )
    op.create_table(
        "tax_benefits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("benefit_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("tax_year BETWEEN 1900 AND 9999", name="ck_tax_benefits_tax_year"),
        sa.CheckConstraint("amount_kopecks >= 0", name="ck_tax_benefits_amount_nonnegative"),
        sa.CheckConstraint(
            "status IN ('planned', 'submitted', 'received', 'rejected')",
            name="ck_tax_benefits_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "tax_year",
            "benefit_type",
            name="uq_tax_benefits_account_year_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("tax_benefits")
    op.drop_table("iis_contributions")
    op.drop_table("iis_profiles")
