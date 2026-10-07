"""Empty append-only H2-B1 portfolio dependency bindings; no financial backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0053_historical_portfolio_flows"
down_revision = "0052_source_cash_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_portfolio_dependency_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("row_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("flow_id", sa.String(64), nullable=True),
        sa.Column("mapping_kind", sa.String(16), nullable=True),
        sa.Column("covered_from", sa.Date(), nullable=True),
        sa.Column("covered_to", sa.Date(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "historical_portfolio_flow_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "flow_id", sa.String(64), sa.ForeignKey("historical_owner_flows.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.Integer(),
            sa.ForeignKey("historical_portfolio_flow_revisions.id"),
            nullable=True,
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("acceptance_state", sa.String(16), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("material_signature", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(material_signature) = 64", name="ck_portfolio_flow_material"),
        sa.CheckConstraint("revision > 0", name="ck_portfolio_flow_revision"),
        sa.CheckConstraint(
            "(operation IN ('accept', 'reaffirm') AND acceptance_state = 'accepted' AND reason_code IS NULL) OR (operation = 'retire' AND acceptance_state = 'retired' AND reason_code IS NOT NULL) OR (operation = 'revoke' AND acceptance_state = 'revoked' AND reason_code IS NOT NULL)",
            name="ck_portfolio_flow_revision_state",
        ),
        sa.UniqueConstraint("flow_id", "revision", name="uq_portfolio_flow_revision"),
    )
    op.create_table(
        "historical_portfolio_flow_applies",
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
            sa.ForeignKey("historical_portfolio_flow_revisions.id"),
            nullable=False,
        ),
        sa.Column("result_action", sa.String(16), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result_action IN ('accepted', 'reaffirmed', 'revoked', 'noop')",
            name="ck_portfolio_flow_apply_result",
        ),
        sa.UniqueConstraint("request_id", name="uq_portfolio_flow_request"),
    )

    _dependency_triggers()
    for table in (
        "historical_portfolio_flow_revisions",
        "historical_portfolio_flow_applies",
        "historical_portfolio_dependency_changes",
    ):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'historical portfolio history is append-only'); END"
                )
            )


def downgrade() -> None:
    tables = ("historical_portfolio_flow_applies", "historical_portfolio_flow_revisions")
    if any(op.get_bind().execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in tables):
        raise RuntimeError("cannot discard historical portfolio acceptance")
    for table in tables:
        op.drop_table(table)
    for table in _DEPENDENCY_TABLES:
        for operation in ("insert", "update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER portfolio_change_{table}_{operation}"))
    op.drop_table("historical_portfolio_dependency_changes")


_DEPENDENCY_TABLES = (
    "accounts",
    "account_performance_scope_memberships",
    "broker_identity_mappings",
    "mybroker_imports",
    "historical_owner_flow_revisions",
    "historical_owner_flow_occurrences",
    "external_flows",
    "external_transfer_links",
    "external_transfer_reconciliation_evidence",
    "cash_boundary_coverages",
    "in_kind_boundary_coverages",
    "class_no_crossing_coverages",
)


def _dependency_triggers():
    """Capture old/new relevance without payloads, including SQL bypass and ABA.

    Hooks retire sanctioned acceptances; the monotonic journal independently
    invalidates reads even when a SQL writer restores the same material.
    No-op writer reservations generate no events.
    """
    for table in _DEPENDENCY_TABLES:
        columns = [r[1] for r in op.get_bind().execute(sa.text(f"PRAGMA table_info({table})"))]
        material = ["id", "account_type"] if table == "accounts" else columns
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in material)
        for operation, aliases in (
            ("INSERT", ("NEW",)),
            ("UPDATE", ("OLD", "NEW")),
            ("DELETE", ("OLD",)),
        ):
            statements = []
            for alias in aliases:
                account = f"{alias}.account_id" if "account_id" in columns else "NULL"
                flow = f"{alias}.flow_id" if "flow_id" in columns else "NULL"
                kind = f"{alias}.subject_kind" if table == "broker_identity_mappings" else "NULL"
                start = end = "NULL"
                if table == "account_performance_scope_memberships":
                    start, end = f"{alias}.effective_from", f"{alias}.effective_to"
                elif "covered_from" in columns:
                    start, end = f"{alias}.covered_from", f"{alias}.covered_to"
                elif table.startswith("historical_owner_flow_"):
                    start = end = f"(SELECT event_date FROM historical_owner_flows WHERE id={flow})"
                elif table in (
                    "external_flows",
                    "external_transfer_links",
                    "external_transfer_reconciliation_evidence",
                ):
                    link = (
                        f"{alias}.id"
                        if table == "external_transfer_links"
                        else f"{alias}.transfer_link_id"
                    )
                    resolved = (
                        f"(SELECT status FROM external_transfer_links WHERE id={link}) = 'resolved'"
                    )
                    count = (
                        f"(SELECT COUNT(*) FROM external_flows WHERE transfer_link_id={link}) = 2"
                    )
                    for field, aggregate in (("start", "MIN"), ("end", "MAX")):
                        span = f"CASE WHEN {resolved} AND {count} THEN (SELECT {aggregate}(event_date) FROM external_flows WHERE transfer_link_id={link}) ELSE NULL END"
                        if table == "external_flows":
                            span = (
                                f"CASE WHEN {link} IS NULL THEN {alias}.event_date ELSE {span} END"
                            )
                        if field == "start":
                            start = span
                        else:
                            end = span
                statements.append(
                    "INSERT INTO historical_portfolio_dependency_changes "
                    "(table_name,row_id,account_id,flow_id,mapping_kind,covered_from,covered_to) "
                    f"SELECT '{table}',{alias}.id,{account},{flow},{kind},{start},{end}"
                    + (
                        f" WHERE {alias}.provenance_kind <> 'owner_attested_source_cash_history'"
                        if table == "cash_boundary_coverages"
                        else ""
                    )
                    + ";"
                )
            condition = f"WHEN {changed} " if operation == "UPDATE" else ""
            op.execute(
                sa.text(
                    f"CREATE TRIGGER portfolio_change_{table}_{operation.lower()} AFTER {operation} ON {table} "
                    + condition
                    + "BEGIN "
                    + " ".join(statements)
                    + " END"
                )
            )
