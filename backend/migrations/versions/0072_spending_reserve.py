"""Owner-selected spending reserve plan, independent of reporting month facts."""
import sqlalchemy as sa
from alembic import op

revision = "0072_spending_reserve"
down_revision = "0071_spending_payment_rules"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "spending_reserve_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 1 AND revision >= 1", name="ck_spending_reserve_singleton"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM spending_reserve_plans LIMIT 1")).first():
        raise RuntimeError("Saved reserve plan requires forward recovery")
    op.drop_table("spending_reserve_plans")
