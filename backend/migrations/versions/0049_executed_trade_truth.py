"""Empty canonical execution ledger. No source or financial backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0049_executed_trade_truth"
down_revision = "0048_mybroker_import_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "executed_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("source_account", sa.String(128), nullable=False),
        sa.Column("primary_id", sa.String(128), nullable=False),
        sa.Column("secondary_id", sa.String(128), nullable=False),
        sa.Column("source_identity", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("core_json", sa.Text(), nullable=False),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "source_account",
            "primary_id",
            "secondary_id",
            name="uq_executed_trade_alias",
        ),
        sa.UniqueConstraint("source_identity", name="uq_executed_trade_source_identity"),
        sa.CheckConstraint("length(source_identity) = 64", name="ck_executed_trade_identity"),
    )
    op.create_table(
        "executed_trade_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("executed_trades.id"), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("mybroker_imports.id"), nullable=False),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("import_id", "section", "ordinal", name="uq_trade_occurrence"),
    )
    op.create_table(
        "executed_trade_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("executed_trades.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("acceptance_state", sa.String(16), nullable=False),
        sa.Column("fee_basis", sa.String(16), nullable=False),
        sa.Column("event_c1_json", sa.Text()),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("material_fingerprint", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trade_id", "revision", name="uq_trade_revision"),
        sa.CheckConstraint("revision > 0", name="ck_trade_revision_positive"),
        sa.CheckConstraint("lifecycle IN ('pending', 'settled')", name="ck_trade_lifecycle"),
        sa.CheckConstraint(
            "fee_basis IN ('zero', 'separate', 'embedded', 'unknown')", name="ck_trade_fee_basis"
        ),
        sa.CheckConstraint(
            "acceptance_state IN ('active', 'superseded', 'retracted')", name="ck_trade_acceptance"
        ),
    )
    op.create_table(
        "executed_trade_applies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("trade_ids_json", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_trade_apply_request"),
    )


def downgrade() -> None:
    tables = (
        "executed_trade_applies",
        "executed_trade_revisions",
        "executed_trade_occurrences",
        "executed_trades",
    )
    if any(
        op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() for table in tables
    ):
        raise RuntimeError("cannot discard canonical executed-trade truth")
    for table in tables:
        op.drop_table(table)
