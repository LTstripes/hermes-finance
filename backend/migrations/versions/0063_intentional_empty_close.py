"""Append-only intentional-empty Close audit; no economic or legacy month changes."""

import sqlalchemy as sa
from alembic import op

revision = "0063_intentional_empty_close"
down_revision = "0062_security_reg_isin_mappings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intentional_empty_close_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), unique=True, nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("month_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("expected_identity", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(reason)) BETWEEN 1 AND 2000", name="ck_empty_close_reason"),
        sa.CheckConstraint(
            "length(expected_identity) = 64 AND length(intent_digest) = 64",
            name="ck_empty_close_digests",
        ),
        sa.CheckConstraint(
            "policy_version = 'intentional_empty_manual_month_v1'", name="ck_empty_close_policy"
        ),
        sa.CheckConstraint(
            "month_id > 0 AND year BETWEEN 1 AND 9999 AND month BETWEEN 1 AND 12",
            name="ck_empty_close_period",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_empty_close_month", "intentional_empty_close_receipts", ["month_id", "id"])
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER empty_close_receipt_no_{operation.lower()} "
            f"BEFORE {operation} ON intentional_empty_close_receipts "
            "BEGIN SELECT RAISE(ABORT, 'intentional empty Close audit is immutable'); END"
        )


def downgrade():
    # Never discard a financial lifecycle decision to make old code run.
    if (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM intentional_empty_close_receipts"))
        .scalar()
    ):
        raise RuntimeError("cannot downgrade populated intentional empty Close audit")
    op.drop_table("intentional_empty_close_receipts")
