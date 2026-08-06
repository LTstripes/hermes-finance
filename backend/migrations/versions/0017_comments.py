"""Create monthly comment records.

Revision ID: 0017_comments
Revises: 0016_goals
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_comments"
down_revision = "0016_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_monthly_comments_position_positive"),
        sa.CheckConstraint("length(text) > 0", name="ck_monthly_comments_text_nonempty"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporting_month_id", "position", name="uq_monthly_comments_month_position"
        ),
    )


def downgrade() -> None:
    op.drop_table("monthly_comments")
