"""Create goal records.

Revision ID: 0016_goals
Revises: 0015_properties
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_goals"
down_revision = "0015_properties"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("goal_type", sa.String(length=32), nullable=False),
        sa.Column("target_value_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("calculation_mode", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "goal_type IN ('passive_income', 'capital', 'expense_coverage', "
            "'mortgage_coverage', 'other')",
            name="ck_goals_goal_type",
        ),
        sa.CheckConstraint("target_value_kopecks >= 0", name="ck_goals_target_value_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("goals")
