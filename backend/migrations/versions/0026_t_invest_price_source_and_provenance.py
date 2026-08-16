"""Add t_invest price source and snapshot-scoped quote provenance.

Revision ID: 0026_t_invest_price_source_and_provenance
Revises: 0025_provider_neutral_market_identity
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_t_invest_price_source_and_provenance"
down_revision = "0025_provider_neutral_market_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_snapshots_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("average_cost_per_unit_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("market_price_per_unit_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("accrued_interest_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("market_value_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("cost_basis_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("unrealized_result_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column(
            "price_source", sa.String(length=16), server_default=sa.text("'manual'"), nullable=False
        ),
        sa.Column("manual_adjustment", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_position_snapshots_quantity_nonnegative"),
        sa.CheckConstraint(
            "average_cost_per_unit_kopecks >= 0",
            name="ck_position_snapshots_average_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "market_price_per_unit_kopecks >= 0",
            name="ck_position_snapshots_market_price_nonnegative",
        ),
        sa.CheckConstraint(
            "accrued_interest_kopecks IS NULL OR accrued_interest_kopecks >= 0",
            name="ck_position_snapshots_accrued_interest_nonnegative",
        ),
        sa.CheckConstraint(
            "market_value_kopecks >= 0",
            name="ck_position_snapshots_market_value_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_basis_kopecks >= 0",
            name="ck_position_snapshots_cost_basis_nonnegative",
        ),
        sa.CheckConstraint(
            "price_source IN ('manual', 'moex', 'alfa_pdf', 't_invest')",
            name="ck_position_snapshots_price_source",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            name="uq_position_snapshots_month_account_instrument",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO position_snapshots_new ("
            "id, reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "accrued_interest_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "notes, updated_at"
            ") SELECT "
            "id, reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "accrued_interest_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "notes, updated_at "
            "FROM position_snapshots"
        )
    )
    op.drop_table("position_snapshots")
    op.rename_table("position_snapshots_new", "position_snapshots")

    op.create_table(
        "position_quote_provenance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_instrument_id", sa.String(length=128), nullable=False),
        sa.Column("provider_venue_id", sa.String(length=96), nullable=True),
        sa.Column("quote_kind", sa.String(length=16), nullable=False),
        sa.Column("raw_price", sa.String(length=32), nullable=False),
        sa.Column("raw_price_basis", sa.String(length=8), nullable=False),
        sa.Column("normalized_price_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("fetched_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("freshness", sa.String(length=16), nullable=False),
        sa.Column("applied_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalized_price_kopecks >= 0",
            name="ck_position_quote_provenance_price_nonnegative",
        ),
        sa.CheckConstraint(
            "freshness IN ('ok', 'stale')",
            name="ck_position_quote_provenance_freshness",
        ),
        sa.CheckConstraint(
            "quote_kind IN ('last', 'history')",
            name="ck_position_quote_provenance_quote_kind",
        ),
        sa.CheckConstraint(
            "raw_price_basis IN ('R', 'F')",
            name="ck_position_quote_provenance_basis",
        ),
        sa.ForeignKeyConstraint(
            ["position_snapshot_id"],
            ["position_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_position_quote_provenance_snapshot_id",
        "position_quote_provenance",
        ["position_snapshot_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    provenance_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM position_quote_provenance")
    ).scalar_one()
    if provenance_count:
        raise ValueError("cannot downgrade while quote provenance rows exist")
    t_invest_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM position_snapshots WHERE price_source = 't_invest'")
    ).scalar_one()
    if t_invest_count:
        raise ValueError("cannot downgrade while t_invest price_source rows exist")
    op.drop_index(
        "ix_position_quote_provenance_snapshot_id",
        table_name="position_quote_provenance",
    )
    op.drop_table("position_quote_provenance")
    op.create_table(
        "position_snapshots_old",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("average_cost_per_unit_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("market_price_per_unit_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("accrued_interest_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("market_value_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("cost_basis_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("unrealized_result_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column(
            "price_source", sa.String(length=16), server_default=sa.text("'manual'"), nullable=False
        ),
        sa.Column("manual_adjustment", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_position_snapshots_quantity_nonnegative"),
        sa.CheckConstraint(
            "average_cost_per_unit_kopecks >= 0",
            name="ck_position_snapshots_average_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "market_price_per_unit_kopecks >= 0",
            name="ck_position_snapshots_market_price_nonnegative",
        ),
        sa.CheckConstraint(
            "accrued_interest_kopecks IS NULL OR accrued_interest_kopecks >= 0",
            name="ck_position_snapshots_accrued_interest_nonnegative",
        ),
        sa.CheckConstraint(
            "market_value_kopecks >= 0",
            name="ck_position_snapshots_market_value_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_basis_kopecks >= 0",
            name="ck_position_snapshots_cost_basis_nonnegative",
        ),
        sa.CheckConstraint(
            "price_source IN ('manual', 'moex', 'alfa_pdf')",
            name="ck_position_snapshots_price_source",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporting_month_id",
            "account_id",
            "instrument_id",
            name="uq_position_snapshots_month_account_instrument",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO position_snapshots_old ("
            "id, reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "accrued_interest_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "notes, updated_at"
            ") SELECT "
            "id, reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "accrued_interest_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "notes, updated_at "
            "FROM position_snapshots"
        )
    )
    op.drop_table("position_snapshots")
    op.rename_table("position_snapshots_old", "position_snapshots")
