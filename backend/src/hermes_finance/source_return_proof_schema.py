"""Additive source-only proof guards. Never change V1 intake revisions."""

from sqlalchemy import event

TABLES = ("source_return_proofs", "source_return_proof_dependencies")
DEPENDENCIES = (
    "source_intake_money_classifications",
    "security_reg_isin_mappings",
    "reporting_months",
)
# Immutable source membership/heads and correction chains already carry their
# own append-only revisions. Catalogue/financial changes advance existing V1
# dependency revisions. Only these three mutable inputs need new ABA tokens.


def install_sql_guards(connection):
    for table in TABLES:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} "
                f"BEFORE {operation} ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'source return proof is append-only'); END"
            )
    for table in DEPENDENCIES:
        columns = [row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
        for operation in ("INSERT", "UPDATE", "DELETE"):
            changed = " OR ".join(f"OLD.{column} IS NOT NEW.{column}" for column in columns)
            condition = "EXISTS (SELECT 1 FROM source_intake_originals)"
            if operation == "UPDATE":
                condition += f" AND ({changed})"
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS return_proof_{table}_{operation.lower()} "
                f"AFTER {operation} ON {table} WHEN {condition} BEGIN "
                "INSERT INTO source_return_proof_dependencies(token) VALUES(lower(hex(randomblob(32)))); END"
            )


def _after_create(_metadata, connection, **_kwargs):
    install_sql_guards(connection)


def install_hooks():
    from hermes_finance.persistence import Base

    if not event.contains(Base.metadata, "after_create", _after_create):
        event.listen(Base.metadata, "after_create", _after_create)
