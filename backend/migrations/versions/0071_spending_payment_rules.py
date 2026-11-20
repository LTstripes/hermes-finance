"""Owner notes and optional payment schedules, independent of closed month facts."""

import sqlalchemy as sa
from alembic import op

revision = "0071_spending_payment_rules"
down_revision = "0070_spending_screen"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "spending_payment_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "operation_id",
            sa.Integer(),
            sa.ForeignKey("spending_operations.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column(
            "entry_id",
            sa.Integer(),
            sa.ForeignKey("expense_entries.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("mandatory_override", sa.Boolean()),
        sa.Column("repeat", sa.Boolean(), nullable=False),
        sa.Column("was_recurring", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("period_months", sa.Integer()),
        sa.Column("next_due", sa.Date()),
        sa.Column("amount_kopecks", sa.BigInteger()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("operation_id IS NULL OR entry_id IS NULL"),
        sa.CheckConstraint("period_months IS NULL OR period_months > 0"),
        sa.CheckConstraint("amount_kopecks IS NULL OR amount_kopecks >= 0"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_spending_payment_rules_month", "spending_payment_rules", ["month"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM spending_payment_rules LIMIT 1")).first():
        raise RuntimeError("cannot discard owner payment notes or schedules")
    op.drop_table("spending_payment_rules")
