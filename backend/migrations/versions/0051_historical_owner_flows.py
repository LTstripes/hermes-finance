"""Empty H2-A1 immutable cores, occurrence owners, revisions and receipts.

No financial backfill or monthly materialization. SQL guards preserve history.
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_historical_owner_flows"
down_revision = "0050_historical_endpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_owner_flows",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("signed_source_amount", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("boundary_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("boundary_amount_kopecks > 0", name="ck_owner_flow_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_owner_flow_currency"),
        sa.CheckConstraint(
            "direction IN ('contribution', 'withdrawal')", name="ck_owner_flow_direction"
        ),
    )
    op.create_table(
        "historical_owner_flow_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "flow_id", sa.String(64), sa.ForeignKey("historical_owner_flows.id"), nullable=False
        ),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("mybroker_imports.id"), nullable=False),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("row_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("section = 'money' AND ordinal >= 0", name="ck_owner_flow_occurrence"),
        sa.CheckConstraint("length(row_fingerprint) = 64", name="ck_owner_flow_row_fingerprint"),
        sa.UniqueConstraint("import_id", "section", "ordinal", name="uq_owner_flow_occurrence"),
    )
    op.create_table(
        "historical_owner_flow_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "flow_id", sa.String(64), sa.ForeignKey("historical_owner_flows.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.Integer(),
            sa.ForeignKey("historical_owner_flow_revisions.id"),
            nullable=True,
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("acceptance_state", sa.String(16), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("material_signature", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(material_signature) = 64", name="ck_owner_flow_material"),
        sa.CheckConstraint("revision > 0", name="ck_owner_flow_revision"),
        sa.CheckConstraint(
            "(operation IN ('accept', 'corroborate', 'reaffirm') AND acceptance_state = 'accepted' AND reason_code IS NULL) OR (operation = 'retire' AND acceptance_state = 'retired' AND reason_code IS NOT NULL) OR (operation = 'revoke' AND acceptance_state = 'revoked' AND reason_code IS NOT NULL)",
            name="ck_owner_flow_revision_state",
        ),
        sa.UniqueConstraint("flow_id", "revision", name="uq_owner_flow_revision"),
    )
    op.create_table(
        "historical_owner_flow_applies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column(
            "flow_id", sa.String(64), sa.ForeignKey("historical_owner_flows.id"), nullable=False
        ),
        sa.Column(
            "revision_id",
            sa.Integer(),
            sa.ForeignKey("historical_owner_flow_revisions.id"),
            nullable=False,
        ),
        sa.Column("result_action", sa.String(16), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result_action IN ('created', 'corroborated', 'reaffirmed', 'revoked', 'noop')",
            name="ck_owner_flow_apply_result",
        ),
        sa.UniqueConstraint("request_id", name="uq_owner_flow_request"),
    )
    for table in (
        "historical_owner_flows",
        "historical_owner_flow_occurrences",
        "historical_owner_flow_revisions",
        "historical_owner_flow_applies",
    ):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'historical owner flow history is append-only'); END"
                )
            )


def downgrade() -> None:
    tables = (
        "historical_owner_flow_applies",
        "historical_owner_flow_revisions",
        "historical_owner_flow_occurrences",
        "historical_owner_flows",
    )
    if any(op.get_bind().execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in tables):
        raise RuntimeError("cannot discard historical owner flow acceptance")
    for table in tables:
        op.drop_table(table)
