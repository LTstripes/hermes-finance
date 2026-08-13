"""Add the explicit passive-income history lower boundary.

Revision ID: 0023_passive_income_history_eligibility
Revises: 0022_goal_main_selection
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_passive_income_history_eligibility"
down_revision = "0022_goal_main_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("passive_income_history_start_month", sa.String(length=7), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_column("passive_income_history_start_month")
