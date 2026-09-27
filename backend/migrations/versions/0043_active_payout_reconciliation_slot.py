"""Retain historical reconciliation while releasing a manual flow for correction.

Revision ID: 0043_active_payout_reconciliation_slot
Revises: 0042_payout_provenance_lifecycle
"""

import sqlalchemy as sa
from alembic import op

revision = "0043_active_payout_reconciliation_slot"
down_revision = "0042_payout_provenance_lifecycle"
branch_labels = None
depends_on = None

TABLE = "applied_payout_reconciliations"
ACTIVE_INDEX = "uq_applied_payout_reconciliations_active_manual_flow"
MANUAL_FK = "fk_applied_payout_reconciliations_expected_cash_flow_id"
FK_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    with op.batch_alter_table(TABLE, naming_convention=FK_NAMING) as batch:
        batch.add_column(sa.Column("archived_from_period", sa.String(7), nullable=True))
        batch.drop_constraint("uq_applied_payout_reconciliations_manual_flow", type_="unique")
        batch.drop_constraint(
            "fk_applied_payout_reconciliations_expected_cash_flow_id_expected_cash_flows",
            type_="foreignkey",
        )
        batch.create_foreign_key(
            MANUAL_FK,
            "expected_cash_flows",
            ["expected_cash_flow_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(
        sa.text(
            "UPDATE applied_payout_reconciliations "
            "SET archived_from_period = ("
            "SELECT archived_from_period FROM applied_provider_payouts "
            "WHERE applied_provider_payouts.id = applied_payout_reconciliations.applied_payout_id"
            ") WHERE applied_payout_id IN ("
            "SELECT id FROM applied_provider_payouts WHERE reporting_month_id IS NULL"
            ")"
        )
    )
    op.create_index(
        ACTIVE_INDEX,
        TABLE,
        ["expected_cash_flow_id"],
        unique=True,
        sqlite_where=sa.text("archived_from_period IS NULL"),
    )
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("payout reconciliation migration left an invalid FK graph")


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text(
            "SELECT count(*) FROM applied_payout_reconciliations "
            "WHERE archived_from_period IS NOT NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade payout reconciliation with historical links")
    op.drop_index(ACTIVE_INDEX, table_name=TABLE)
    with op.batch_alter_table(TABLE, naming_convention=FK_NAMING) as batch:
        batch.drop_constraint(MANUAL_FK, type_="foreignkey")
        batch.create_foreign_key(
            "fk_applied_payout_reconciliations_expected_cash_flow_id_expected_cash_flows",
            "expected_cash_flows",
            ["expected_cash_flow_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_column("archived_from_period")
        batch.create_unique_constraint(
            "uq_applied_payout_reconciliations_manual_flow", ["expected_cash_flow_id"]
        )
    if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("payout reconciliation downgrade left an invalid FK graph")
