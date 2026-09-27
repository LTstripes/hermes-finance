"""Allow draft snapshot removal while retaining payout identity and revisions.

Revision ID: 0042_payout_provenance_lifecycle
Revises: 0041_debt_linked_account
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_payout_provenance_lifecycle"
down_revision = "0041_debt_linked_account"
branch_labels = None
depends_on = None


def _rebuild_tables(action: str) -> None:
    """Rebuild referenced tables under the migration connection's FK guard.

    The migration environment checks the complete graph before committing.
    """
    connection = op.get_bind()
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("SQLite batch copy requires migration-scoped FK suspension")
    tables = (
        ("position_snapshots", "expected_cash_flows", "applied_provider_payouts")
        if action == "upgrade"
        else ("applied_provider_payouts", "expected_cash_flows", "position_snapshots")
    )
    for table in tables:
        with op.batch_alter_table(table) as batch:
            if action == "upgrade":
                batch.alter_column("reporting_month_id", existing_type=sa.Integer(), nullable=True)
                batch.add_column(sa.Column("archived_from_period", sa.String(7), nullable=True))
                batch.create_check_constraint(
                    f"ck_{table}_archive_scope",
                    "(reporting_month_id IS NULL AND archived_from_period IS NOT NULL) OR "
                    "(reporting_month_id IS NOT NULL AND archived_from_period IS NULL)",
                )
            else:
                batch.drop_constraint(f"ck_{table}_archive_scope", type_="check")
                batch.drop_column("archived_from_period")
                batch.alter_column("reporting_month_id", existing_type=sa.Integer(), nullable=False)
    if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("payout lifecycle migration left an invalid FK graph")


def upgrade() -> None:
    _rebuild_tables("upgrade")


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("position_snapshots", "expected_cash_flows", "applied_provider_payouts"):
        count = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE reporting_month_id IS NULL")
        ).scalar_one()
        if count:
            raise RuntimeError(f"cannot downgrade payout lifecycle with archived {table}")
    _rebuild_tables("downgrade")
