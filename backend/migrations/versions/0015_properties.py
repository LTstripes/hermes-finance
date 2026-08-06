"""Create property snapshot records.

Revision ID: 0015_properties
Revises: 0014_debts
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_properties"
down_revision = "0014_debts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("estimated_value_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("mortgage_balance_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("monthly_payment_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "estimated_value_kopecks >= 0", name="ck_property_snapshots_value_nonnegative"
        ),
        sa.CheckConstraint(
            "mortgage_balance_kopecks >= 0", name="ck_property_snapshots_mortgage_nonnegative"
        ),
        sa.CheckConstraint(
            "monthly_payment_kopecks >= 0", name="ck_property_snapshots_payment_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("property_snapshots")
