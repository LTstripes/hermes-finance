"""Add #336 financial-context facts: debt terms, mortgage rate, planned budget.

Revision ID: 0037_336_financial_context
Revises: 0036_broker_baseline_provenance

Additive owner-entered contract only (#336). No backfill and no guesses:
every new column is NULL (unknown) for pre-existing rows. ``0`` stays an
explicit owner statement, never a migration default. ``ALTER`` of columns
and check constraints runs through ``batch_alter_table`` because SQLite
cannot alter constraints in place.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_336_financial_context"
down_revision = "0036_broker_baseline_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("debts") as batch_op:
        batch_op.add_column(sa.Column("annual_rate_basis_points", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("next_due_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("contract_end_date", sa.Date(), nullable=True))
        batch_op.create_check_constraint(
            "ck_debts_annual_rate_nonnegative",
            "annual_rate_basis_points IS NULL OR annual_rate_basis_points >= 0",
        )

    op.create_table(
        "planned_budget_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("planned_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("expense_type", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "expense_type IN ('mandatory', 'comfortable', 'other')",
            name="ck_planned_budget_lines_expense_type",
        ),
        sa.CheckConstraint(
            "planned_amount_kopecks >= 0",
            name="ck_planned_budget_lines_amount_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_planned_budget_lines_month",
        "planned_budget_lines",
        ["reporting_month_id"],
    )

    with op.batch_alter_table("property_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column("mortgage_annual_rate_basis_points", sa.Integer(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_property_snapshots_mortgage_rate_nonnegative",
            "mortgage_annual_rate_basis_points IS NULL OR mortgage_annual_rate_basis_points >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("property_snapshots") as batch_op:
        batch_op.drop_constraint("ck_property_snapshots_mortgage_rate_nonnegative", type_="check")
        batch_op.drop_column("mortgage_annual_rate_basis_points")

    op.drop_index("ix_planned_budget_lines_month", table_name="planned_budget_lines")
    op.drop_table("planned_budget_lines")

    with op.batch_alter_table("debts") as batch_op:
        batch_op.drop_constraint("ck_debts_annual_rate_nonnegative", type_="check")
        batch_op.drop_column("contract_end_date")
        batch_op.drop_column("next_due_date")
        batch_op.drop_column("annual_rate_basis_points")
