"""Empty H1-A acceptance and receipt tables; no historical materialization."""

import sqlalchemy as sa
from alembic import op

revision = "0050_historical_endpoints"
down_revision = "0049_executed_trade_truth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_endpoint_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint_key", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column("basis", sa.String(8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id", sa.Integer(), sa.ForeignKey("historical_endpoint_revisions.id")
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("acceptance_state", sa.String(16), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("material_signature", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("endpoint_key", "revision", name="uq_historical_endpoint_revision"),
        sa.CheckConstraint("revision > 0", name="ck_historical_endpoint_revision"),
        sa.CheckConstraint(
            "basis = 'eod' AND currency = 'RUB'", name="ck_historical_endpoint_basis"
        ),
        sa.CheckConstraint(
            "operation IN ('accept', 'reaffirm', 'retire', 'revoke')",
            name="ck_historical_endpoint_operation",
        ),
        sa.CheckConstraint(
            "(operation IN ('accept', 'reaffirm') AND acceptance_state = 'accepted' "
            "AND reason_code IS NULL) OR (operation = 'retire' AND acceptance_state = 'retired' "
            "AND reason_code IS NOT NULL) OR (operation = 'revoke' AND acceptance_state = 'revoked' "
            "AND reason_code IS NOT NULL)",
            name="ck_historical_endpoint_state",
        ),
        sa.CheckConstraint(
            "length(material_signature) = 64", name="ck_historical_endpoint_material"
        ),
    )
    op.create_table(
        "historical_endpoint_applies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("endpoint_key", sa.String(64), nullable=False),
        sa.Column(
            "revision_id",
            sa.Integer(),
            sa.ForeignKey("historical_endpoint_revisions.id"),
            nullable=False,
        ),
        sa.Column("result_action", sa.String(16), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_historical_endpoint_request"),
        sa.CheckConstraint(
            "result_action IN ('created', 'reaffirmed', 'revoked', 'noop')",
            name="ck_historical_endpoint_result",
        ),
    )
    # Acceptance/receipts are durable history, including through direct SQL writers.
    for table in ("historical_endpoint_revisions", "historical_endpoint_applies"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'historical endpoint history is append-only'); END"
                )
            )


def downgrade() -> None:
    tables = ("historical_endpoint_applies", "historical_endpoint_revisions")
    if any(op.get_bind().execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in tables):
        raise RuntimeError("cannot discard historical endpoint acceptance")
    for table in tables:
        op.drop_table(table)
