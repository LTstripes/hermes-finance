"""Distinguish saved actuals from cloned settings without guessing legacy history."""

import sqlalchemy as sa
from alembic import op

revision = "0064_month_template_provenance"
down_revision = "0063_intentional_empty_close"
branch_labels = None
depends_on = None

TABLES = ("income_entries", "expense_entries", "saving_allocations")


def upgrade():
    for table in TABLES:
        # NULL is deliberately unknown. Never infer acceptance from old amounts,
        # recurrence or received_at; older clones did not persist this distinction.
        op.add_column(table, sa.Column("actual_fact_origin", sa.String(32), nullable=True))


def downgrade():
    # Old code treats templates as actuals. Never silently erase known provenance.
    # Also preserve 0063's refusal BEFORE any DDL in a downgrade chain to 0062.
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM intentional_empty_close_receipts LIMIT 1"))
        .first()
    ):
        raise RuntimeError("cannot downgrade populated intentional empty Close audit")
    for table in TABLES:
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT 1 FROM {table} WHERE actual_fact_origin IS NOT NULL LIMIT 1"))
            .first()
        ):
            raise RuntimeError("cannot downgrade populated month template provenance")
    for table in TABLES:
        op.drop_column(table, "actual_fact_origin")
