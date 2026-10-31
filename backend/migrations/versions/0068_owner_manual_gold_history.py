"""Empty append-only Owner gold evidence; no financial or historical backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0068_owner_manual_gold_history"
down_revision = "0067_investment_report_proofs"
branch_labels = None
depends_on = None

TABLES = (
    "owner_manual_gold_histories",
    "owner_manual_gold_history_revisions",
    "owner_manual_gold_history_applies",
)


def upgrade():
    op.create_table(
        TABLES[0],
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "instrument_id", name="uq_owner_gold_scope"),
    )
    op.create_table(
        TABLES[1],
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("history_id", sa.Integer(), sa.ForeignKey(TABLES[0] + ".id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("declaration_json", sa.Text(), nullable=False),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column("material_fingerprint", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("history_id", "revision", name="uq_owner_gold_revision"),
        sa.CheckConstraint("revision > 0", name="ck_owner_gold_revision_positive"),
    )
    op.create_table(
        TABLES[2],
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey(TABLES[1] + ".id"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_owner_gold_request"),
    )
    for table in TABLES:
        for action in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'owner_gold_evidence_is_append_only'); END"
                )
            )


def downgrade():
    if any(
        op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() for table in TABLES
    ):
        raise RuntimeError("cannot discard Owner gold evidence")
    for table in reversed(TABLES):
        for action in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER {table}_no_{action}"))
        op.drop_table(table)
