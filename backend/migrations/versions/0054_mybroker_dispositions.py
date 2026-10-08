"""Append-only reviewed source exclusions; no source rewrite or backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0054_mybroker_dispositions"
down_revision = "0053_historical_portfolio_flows"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mybroker_disposition_sets",
        sa.Column(
            "import_id", sa.Integer(), sa.ForeignKey("mybroker_imports.id"), primary_key=True
        ),
        sa.Column("skipped_isins_json", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
    )
    op.create_table(
        "mybroker_disposition_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("mybroker_disposition_sets.import_id"),
            nullable=False,
        ),
        sa.Column("isin", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id", sa.Integer(), sa.ForeignKey("mybroker_disposition_revisions.id")
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "import_id", "isin", "revision", name="uq_mybroker_disposition_revision"
        ),
        sa.CheckConstraint("revision > 0", name="ck_mybroker_disposition_revision"),
        sa.CheckConstraint(
            "state IN ('accepted','retired','revoked')", name="ck_mybroker_skip_state"
        ),
        sa.CheckConstraint(
            "operation IN ('accept','retire','revoke','reaffirm')",
            name="ck_mybroker_skip_operation",
        ),
    )
    op.create_table(
        "mybroker_disposition_applies",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("mybroker_imports.id"), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("revision_ids_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "mybroker_disposition_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("mybroker_disposition_sets.import_id"),
            nullable=False,
        ),
        sqlite_autoincrement=True,
    )
    install_sql_guards(op.get_bind())


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM mybroker_disposition_sets LIMIT 1")).first():
        raise RuntimeError("cannot discard reviewed source exclusions")
    for table in ("broker_identity_mappings", "accounts", "mybroker_imports"):
        for operation in ("insert", "update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER skip_change_{table}_{operation}"))
    for table in (
        "mybroker_disposition_changes",
        "mybroker_disposition_applies",
        "mybroker_disposition_revisions",
        "mybroker_disposition_sets",
    ):
        op.drop_table(table)


def install_sql_guards(connection):
    """Frozen v1 SQL guards; metadata databases mirror this migration."""
    for table in (
        "mybroker_disposition_sets",
        "mybroker_disposition_revisions",
        "mybroker_disposition_applies",
        "mybroker_disposition_changes",
    ):
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'mybroker disposition history is append-only'); END"
            )
    for table in ("broker_identity_mappings", "accounts", "mybroker_imports"):
        columns = [r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        for action, aliases in (
            ("INSERT", ("NEW",)),
            ("UPDATE", ("OLD", "NEW")),
            ("DELETE", ("OLD",)),
        ):
            statements = []
            for alias in aliases:
                if table == "broker_identity_mappings":
                    condition = f"{alias}.provider = 'alfa_mybroker' AND (({alias}.subject_kind='instrument' AND EXISTS (SELECT 1 FROM json_each(s.skipped_isins_json) WHERE value={alias}.provider_identity)) OR ({alias}.subject_kind='account' AND EXISTS (SELECT 1 FROM json_each(i.mappings_json) b WHERE json_extract(b.value,'$.kind')='account' AND json_extract(b.value,'$.identity')={alias}.provider_identity)))"
                elif table == "accounts":
                    condition = f"EXISTS (SELECT 1 FROM json_each(i.mappings_json) b WHERE json_extract(b.value,'$.kind')='account' AND json_extract(b.value,'$.hermes_id')={alias}.id)"
                else:
                    condition = f"i.id={alias}.id"
                affected = f"SELECT s.import_id FROM mybroker_disposition_sets s JOIN mybroker_imports i ON i.id=s.import_id WHERE {condition}"
                statements.append(
                    f"INSERT INTO mybroker_disposition_changes(import_id) {affected};"
                )
                statements.append(
                    f"INSERT INTO mybroker_disposition_revisions(import_id,isin,revision,previous_revision_id,operation,state,evidence_json,confirmation_digest,recorded_at) SELECT r.import_id,r.isin,r.revision+1,r.id,'retire','retired',r.evidence_json,r.confirmation_digest,CURRENT_TIMESTAMP FROM mybroker_disposition_revisions r WHERE r.import_id IN ({affected}) AND r.state='accepted' AND r.revision=(SELECT MAX(x.revision) FROM mybroker_disposition_revisions x WHERE x.import_id=r.import_id AND x.isin=r.isin);"
                )
            when = f"WHEN {changed}" if action == "UPDATE" else ""
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS skip_change_{table}_{action.lower()} AFTER {action} ON {table} {when} BEGIN {' '.join(statements)} END"
            )
