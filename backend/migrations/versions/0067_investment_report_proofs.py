"""Typed investment-report proof profile on the existing source proof host."""

import sqlalchemy as sa
from alembic import op

from hermes_finance.actual_payout_schema import (
    PROOF_GUARDS_0065,
    PROOF_TABLES_0065,
    _check_integrity,
    _inventory,
    _signature,
    _snapshot,
)
from hermes_finance.source_return_proof_schema import DEPENDENCIES, install_sql_guards

revision = "0067_investment_report_proofs"
down_revision = "0066_actual_payout_links"
branch_labels = None
depends_on = None


OLD = "proof_version = 'source_return_custody_v1'"
NEW = "proof_version IN ('source_return_custody_v1','source_return_investment_v1')"


def _guards(scoped):
    expected = dict(PROOF_GUARDS_0065)
    if scoped:
        for table, marker in zip(DEPENDENCIES, ("m", "r", "p"), strict=True):
            for operation in ("insert", "update", "delete"):
                name = f"return_proof_{table}_{operation}"
                alias = "OLD" if operation == "delete" else "NEW"
                expected[name] = expected[name].replace(
                    "lower(hex(randomblob(32)))",
                    f"'{marker}:' || {alias}.id || ':' || substr(lower(hex(randomblob(32))),1,61-length({alias}.id))",
                )
    return expected


def _profile(connection, *, scoped):
    inventory = _inventory(connection)
    tables = dict(PROOF_TABLES_0065)
    if scoped:
        tables["source_return_proofs"] = tables["source_return_proofs"].replace(OLD, NEW)
    actual_tables = {
        name: _signature(sql)
        for kind, name, _, sql in inventory
        if kind == "table" and name in tables
    }
    actual_guards = {
        name: sql
        for kind, name, table, sql in inventory
        if kind == "trigger" and (table in tables or name.startswith("return_proof_"))
    }
    if actual_tables != {
        name: _signature(sql) for name, sql in tables.items()
    } or actual_guards != _guards(scoped):
        raise RuntimeError("0067_source_return_proof_schema_drift")
    indexes = list(connection.exec_driver_sql("PRAGMA index_list(source_return_proofs)"))
    if (
        len(indexes) != 1
        or tuple(indexes[0][1:]) != ("sqlite_autoindex_source_return_proofs_1", 1, "u", 0)
        or connection.exec_driver_sql(
            "PRAGMA index_info(sqlite_autoindex_source_return_proofs_1)"
        ).all()
        != [(0, 3, "request_id")]
        or connection.exec_driver_sql("PRAGMA index_list(source_return_proof_dependencies)").all()
    ):
        raise RuntimeError("0067_source_return_proof_schema_drift")
    return inventory


def _constraint(expression, *, scoped):
    connection = op.get_bind()
    expected_head = down_revision if scoped else revision
    if connection.exec_driver_sql("SELECT version_num FROM alembic_version").all() != [
        (expected_head,)
    ]:
        raise RuntimeError("0067_exact_single_head_required")
    if (
        connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0
        or not connection.connection.driver_connection.in_transaction
    ):
        raise RuntimeError("0067_requires_reserved_migration_transaction")
    _check_integrity(connection)
    before_schema = _profile(connection, scoped=not scoped)
    columns = {
        name: [row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{name}")')]
        for kind, name, _, _ in before_schema
        if kind == "table" and name != "alembic_version"
    }
    before_rows = _snapshot(connection, columns)
    sequences = dict(connection.exec_driver_sql("SELECT name,seq FROM sqlite_sequence").all())
    for operation in ("update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS source_return_proofs_no_{operation}")
    with op.batch_alter_table(
        "source_return_proofs", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.drop_constraint("ck_source_return_proof_version", type_="check")
        batch.create_check_constraint("ck_source_return_proof_version", expression)
    if "source_return_proofs" in sequences:
        connection.execute(
            sa.text("UPDATE sqlite_sequence SET seq=:seq WHERE name='source_return_proofs'"),
            {"seq": sequences["source_return_proofs"]},
        )
    else:
        connection.exec_driver_sql("DELETE FROM sqlite_sequence WHERE name='source_return_proofs'")
    for table in DEPENDENCIES:
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS return_proof_{table}_{operation}")
    install_sql_guards(connection, scoped=scoped)
    after_schema = _profile(connection, scoped=scoped)

    def untouched(rows):
        return [
            row
            for row in rows
            if row[2] != "source_return_proofs" and row[1] not in _guards(scoped)
        ]

    if (
        untouched(before_schema) != untouched(after_schema)
        or _snapshot(connection, columns) != before_rows
        or dict(connection.exec_driver_sql("SELECT name,seq FROM sqlite_sequence").all())
        != sequences
    ):
        raise RuntimeError("0067_existing_schema_or_rows_changed")
    _check_integrity(connection)


def upgrade():
    _constraint(NEW, scoped=True)


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM source_return_proofs WHERE proof_version='source_return_investment_v1' LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("cannot downgrade populated investment report proof history")
    _constraint(OLD, scoped=False)
