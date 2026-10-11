"""Source-owned broker month receipts; no backfill or economic reinterpretation."""

import sqlalchemy as sa
from alembic import op

revision = "0057_broker_month_batch"
down_revision = "0056_source_native_finance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "broker_month_applies",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column(
            "reporting_month_id",
            sa.Integer(),
            sa.ForeignKey("reporting_months.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("mybroker_imports.id"), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM broker_month_applies")).scalar():
        raise RuntimeError("cannot downgrade with source-owned broker month receipts")
    op.drop_table("broker_month_applies")
