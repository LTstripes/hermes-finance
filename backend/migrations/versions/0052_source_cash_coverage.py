"""Empty H2-A2 revision/receipt layer; no backfill or flow reinterpretation."""

import sqlalchemy as sa
from alembic import op

revision = "0052_source_cash_coverage"
down_revision = "0051_historical_owner_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_cash_coverage_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "coverage_id", sa.Integer(), sa.ForeignKey("cash_boundary_coverages.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id", sa.Integer(), sa.ForeignKey("source_cash_coverage_revisions.id")
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("acceptance_state", sa.String(16), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("material_signature", sa.String(64), nullable=False),
        sa.Column("previous_projection_json", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_source_cash_revision"),
        sa.CheckConstraint("length(material_signature) = 64", name="ck_source_cash_material"),
        sa.CheckConstraint(
            "(operation IN ('accept', 'reaffirm') AND acceptance_state = 'accepted' "
            "AND reason_code IS NULL) OR (operation = 'retire' AND acceptance_state = 'retired' "
            "AND reason_code IS NOT NULL) OR (operation = 'revoke' AND acceptance_state = 'revoked' "
            "AND reason_code IS NOT NULL)",
            name="ck_source_cash_revision_state",
        ),
        sa.UniqueConstraint("coverage_id", "revision", name="uq_source_cash_revision"),
    )
    op.create_table(
        "source_cash_coverage_applies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column(
            "coverage_id", sa.Integer(), sa.ForeignKey("cash_boundary_coverages.id"), nullable=False
        ),
        sa.Column(
            "revision_id",
            sa.Integer(),
            sa.ForeignKey("source_cash_coverage_revisions.id"),
            nullable=False,
        ),
        sa.Column("result_action", sa.String(16), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result_action IN ('created', 'reaffirmed', 'revoked', 'noop')",
            name="ck_source_cash_apply_result",
        ),
        sa.UniqueConstraint("request_id", name="uq_source_cash_request"),
    )
    for table in ("source_cash_coverage_revisions", "source_cash_coverage_applies"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'source cash coverage history is append-only'); END"
                )
            )
    op.execute(
        sa.text(
            "CREATE TRIGGER source_cash_identity_immutable BEFORE UPDATE OF account_id, covered_from, covered_to "
            "ON cash_boundary_coverages WHEN EXISTS (SELECT 1 FROM source_cash_coverage_revisions WHERE coverage_id = OLD.id) "
            "AND (NEW.account_id != OLD.account_id OR NEW.covered_from != OLD.covered_from OR NEW.covered_to != OLD.covered_to) "
            "BEGIN SELECT RAISE(ABORT, 'source cash coverage identity is immutable'); END"
        )
    )


def downgrade() -> None:
    tables = ("source_cash_coverage_applies", "source_cash_coverage_revisions")
    if any(op.get_bind().execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in tables):
        raise RuntimeError("cannot discard source cash coverage acceptance")
    op.execute(sa.text("DROP TRIGGER source_cash_identity_immutable"))
    for table in tables:
        op.drop_table(table)
