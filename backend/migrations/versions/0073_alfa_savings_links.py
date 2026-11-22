"""Explicit local mappings for Alfa savings statement accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0073_alfa_savings_links"
down_revision = "0072_spending_reserve"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alfa_savings_links",
        sa.Column("source_key", sa.String(64), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("account_id", name="uq_alfa_savings_link_account"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM alfa_savings_links LIMIT 1")).first():
        raise RuntimeError("Saved Alfa savings links require forward recovery")
    op.drop_table("alfa_savings_links")
