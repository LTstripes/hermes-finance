"""Nullable source-native totals/net without weakening legacy row requirements.

Downgrade refuses source facts rather than deleting or fabricating money.
"""

import sqlalchemy as sa
from alembic import op

revision = "0056_source_native_finance"
down_revision = "0055_mybroker_corrections"
branch_labels = None
depends_on = None

POSITION_CONTRACT = (
    "(price_source != 'broker_statement_native' AND "
    "average_cost_per_unit_kopecks IS NOT NULL AND market_price_per_unit_kopecks IS NOT NULL AND "
    "cost_basis_kopecks IS NOT NULL AND unrealized_result_kopecks IS NOT NULL AND "
    "source_import_id IS NULL AND source_row_key IS NULL AND native_contract_version IS NULL) OR "
    "(price_source = 'broker_statement_native' AND native_contract_version = 1 AND "
    "native_contract_version IS NOT NULL AND source_import_id IS NOT NULL AND "
    "typeof(market_value_kopecks) = 'integer' AND "
    "source_row_key IS NOT NULL AND length(source_row_key) = 64 AND "
    "historical_instrument_type IS NOT NULL AND historical_instrument_type IN ('stock', 'bond') AND "
    "manual_adjustment = 0 AND "
    "((historical_instrument_type = 'stock' AND bond_nkd_basis = 'not_applicable') OR "
    "(historical_instrument_type = 'bond' AND bond_nkd_basis != 'not_applicable')))"
)
FLOW_CONTRACT = (
    "(amount_basis = 'gross_components' AND gross_amount_kopecks IS NOT NULL AND "
    "tax_amount_kopecks IS NOT NULL AND commission_amount_kopecks IS NOT NULL AND "
    "source_import_id IS NULL AND source_row_key IS NULL) OR "
    "(amount_basis = 'broker_statement_net_v1' AND gross_amount_kopecks IS NULL AND "
    "tax_amount_kopecks IS NULL AND commission_amount_kopecks IS NULL AND "
    "source_import_id IS NOT NULL AND source_row_key IS NOT NULL AND "
    "length(source_row_key) = 64 AND currency = 'RUB' AND "
    "typeof(net_amount_kopecks) = 'integer' AND "
    "flow_type IN ('coupon', 'dividend', 'interest', 'redemption') AND net_amount_kopecks >= 0)"
)
POSITION_OPTIONAL = (
    "average_cost_per_unit_kopecks",
    "market_price_per_unit_kopecks",
    "cost_basis_kopecks",
    "unrealized_result_kopecks",
)
FLOW_OPTIONAL = ("gross_amount_kopecks", "tax_amount_kopecks", "commission_amount_kopecks")


def _require_guard() -> None:
    if op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("SQLite batch copy requires migration-scoped FK suspension")


def upgrade() -> None:
    _require_guard()
    with op.batch_alter_table("position_snapshots") as batch:
        for column in POSITION_OPTIONAL:
            batch.alter_column(column, existing_type=sa.BigInteger(), nullable=True)
        batch.alter_column("price_source", existing_type=sa.String(16), type_=sa.String(32))
        batch.add_column(sa.Column("source_import_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_row_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("native_contract_version", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "bond_nkd_basis", sa.String(16), nullable=False, server_default=sa.text("'unknown'")
            )
        )
        batch.create_foreign_key(
            "fk_position_native_import",
            "mybroker_imports",
            ["source_import_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.drop_constraint("ck_position_snapshots_price_source", type_="check")
        batch.create_check_constraint(
            "ck_position_snapshots_price_source",
            "price_source IN ('manual', 'moex', 'alfa_pdf', 't_invest', 'broker_statement_native')",
        )
        batch.create_check_constraint("ck_position_snapshots_native_contract", POSITION_CONTRACT)
        batch.create_check_constraint(
            "ck_position_snapshots_nkd_basis",
            "bond_nkd_basis IN ('unknown', 'included', 'excluded', 'not_applicable')",
        )
    with op.batch_alter_table("investment_cash_flows") as batch:
        for column in FLOW_OPTIONAL:
            batch.alter_column(column, existing_type=sa.BigInteger(), nullable=True)
        batch.add_column(
            sa.Column(
                "amount_basis",
                sa.String(32),
                nullable=False,
                server_default=sa.text("'gross_components'"),
            )
        )
        batch.add_column(sa.Column("source_import_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_row_key", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_flow_native_import",
            "mybroker_imports",
            ["source_import_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_investment_cash_flows_source_cash", ["account_id", "source_row_key"]
        )
        batch.create_check_constraint("ck_investment_cash_flows_amount_basis", FLOW_CONTRACT)


def downgrade() -> None:
    connection = op.get_bind()
    for table, predicate in (
        ("position_snapshots", "price_source = 'broker_statement_native'"),
        ("investment_cash_flows", "amount_basis != 'gross_components'"),
    ):
        if connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {predicate}")
        ).scalar_one():
            raise RuntimeError("cannot downgrade with source-native financial facts")
    _require_guard()
    with op.batch_alter_table("investment_cash_flows") as batch:
        batch.drop_constraint("ck_investment_cash_flows_amount_basis", type_="check")
        batch.drop_constraint("uq_investment_cash_flows_source_cash", type_="unique")
        batch.drop_constraint("fk_flow_native_import", type_="foreignkey")
        for column in ("amount_basis", "source_import_id", "source_row_key"):
            batch.drop_column(column)
        for column in FLOW_OPTIONAL:
            batch.alter_column(column, existing_type=sa.BigInteger(), nullable=False)
    with op.batch_alter_table("position_snapshots") as batch:
        for name in (
            "ck_position_snapshots_native_contract",
            "ck_position_snapshots_nkd_basis",
            "ck_position_snapshots_price_source",
        ):
            batch.drop_constraint(name, type_="check")
        batch.drop_constraint("fk_position_native_import", type_="foreignkey")
        for column in (
            "source_import_id",
            "source_row_key",
            "native_contract_version",
            "bond_nkd_basis",
        ):
            batch.drop_column(column)
        for column in POSITION_OPTIONAL:
            batch.alter_column(column, existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("price_source", existing_type=sa.String(32), type_=sa.String(16))
        batch.create_check_constraint(
            "ck_position_snapshots_price_source",
            "price_source IN ('manual', 'moex', 'alfa_pdf', 't_invest')",
        )
