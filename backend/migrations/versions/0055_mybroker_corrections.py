"""Empty append-only Skip-to-Map authority; no source or financial backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0055_mybroker_corrections"
down_revision = "0054_mybroker_dispositions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mybroker_correction_applies",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("intent_json", sa.Text(), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("revision_ids_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "mybroker_correction_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("mybroker_imports.id"), nullable=False),
        sa.Column("isin", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id", sa.Integer(), sa.ForeignKey("mybroker_correction_revisions.id")
        ),
        sa.Column(
            "predecessor_revision_id",
            sa.Integer(),
            sa.ForeignKey("mybroker_disposition_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            sa.String(64),
            sa.ForeignKey("mybroker_correction_applies.request_id"),
            nullable=False,
        ),
        sa.Column("binding_json", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "import_id", "isin", "revision", name="uq_mybroker_correction_revision"
        ),
        sa.CheckConstraint("revision > 0", name="ck_mybroker_correction_revision"),
    )
    op.create_table(
        "mybroker_correction_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sqlite_autoincrement=True,
    )
    install_sql_guards(op.get_bind())


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM mybroker_correction_applies LIMIT 1")).first():
        raise RuntimeError("cannot discard reviewed source corrections")
    for table in ("mybroker_imports", "broker_identity_mappings", "accounts", "instruments"):
        for action in ("insert", "update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER correction_change_{table}_{action}"))
    for table in (
        "mybroker_correction_revisions",
        "mybroker_correction_applies",
        "mybroker_correction_changes",
    ):
        op.drop_table(table)


def install_sql_guards(connection):
    """Frozen SQL, also exercised by metadata-database parity tests."""
    for table in (
        "mybroker_correction_applies",
        "mybroker_correction_revisions",
        "mybroker_correction_changes",
    ):
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'mybroker correction history is append-only'); END"
            )
    for table in ("mybroker_imports", "broker_identity_mappings", "accounts", "instruments"):
        columns = [r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        for action in ("INSERT", "UPDATE", "DELETE"):
            when = f"WHEN {changed}" if action == "UPDATE" else ""
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS correction_change_{table}_{action.lower()} AFTER {action} ON {table} {when} BEGIN INSERT INTO mybroker_correction_changes(id) VALUES(NULL); END"
            )
