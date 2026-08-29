"""Persist observed pre/post valuation evidence for external-flow boundaries.

Revision ID: 0034_observed_valuation_boundaries
Revises: 0033_account_scope_membership_history

The tables are additive.  No existing month snapshot, external flow, or
historical membership row is backfilled or reinterpreted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_observed_valuation_boundaries"
down_revision = "0033_account_scope_membership_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_flow_boundary_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("boundary_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('portfolio', 'account')",
            name="ck_external_flow_boundary_groups_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'portfolio' AND account_id IS NULL) OR "
            "(scope = 'account' AND account_id IS NOT NULL)",
            name="ck_external_flow_boundary_groups_scope_account",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            name="fk_external_flow_boundary_groups_month",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_external_flow_boundary_groups_account",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_external_flow_boundary_groups_month_date",
        "external_flow_boundary_groups",
        ["reporting_month_id", "boundary_date"],
    )

    op.create_table(
        "external_flow_boundary_group_members",
        sa.Column("boundary_group_id", sa.Integer(), nullable=False),
        sa.Column("external_flow_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["boundary_group_id"],
            ["external_flow_boundary_groups.id"],
            name="fk_external_flow_boundary_group_members_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_flow_id"],
            ["external_flows.id"],
            name="fk_external_flow_boundary_group_members_flow",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("boundary_group_id", "external_flow_id"),
    )
    op.create_index(
        "ix_external_flow_boundary_group_members_flow",
        "external_flow_boundary_group_members",
        ["external_flow_id"],
    )

    op.create_table(
        "observed_valuation_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("total_value_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("performance_currency", sa.String(length=3), nullable=False),
        sa.Column("coverage_status", sa.String(length=16), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("provenance_kind", sa.String(length=64), nullable=False),
        sa.Column("provenance_reference", sa.String(length=128), nullable=True),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.Column("external_flow_id", sa.Integer(), nullable=True),
        sa.Column("boundary_group_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('portfolio', 'account')",
            name="ck_observed_valuation_points_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'portfolio' AND account_id IS NULL) OR "
            "(scope = 'account' AND account_id IS NOT NULL)",
            name="ck_observed_valuation_points_scope_account",
        ),
        sa.CheckConstraint(
            "total_value_kopecks >= 0",
            name="ck_observed_valuation_points_value_nonnegative",
        ),
        sa.CheckConstraint(
            "length(trim(performance_currency)) = 3",
            name="ck_observed_valuation_points_currency_length",
        ),
        sa.CheckConstraint(
            "coverage_status IN ('complete', 'unavailable', 'unknown')",
            name="ck_observed_valuation_points_coverage",
        ),
        sa.CheckConstraint(
            "quality IN ('exact', 'unavailable', 'unknown')",
            name="ck_observed_valuation_points_quality",
        ),
        sa.CheckConstraint(
            "length(trim(provenance_kind)) > 0",
            name="ck_observed_valuation_points_provenance_kind",
        ),
        sa.CheckConstraint(
            "relation IN ('pre_external_flow', 'post_external_flow')",
            name="ck_observed_valuation_points_relation",
        ),
        sa.CheckConstraint(
            "(external_flow_id IS NOT NULL AND boundary_group_id IS NULL) OR "
            "(external_flow_id IS NULL AND boundary_group_id IS NOT NULL)",
            name="ck_observed_valuation_points_single_boundary_target",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"],
            ["reporting_months.id"],
            name="fk_observed_valuation_points_month",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_observed_valuation_points_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_flow_id"],
            ["external_flows.id"],
            name="fk_observed_valuation_points_flow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["boundary_group_id"],
            ["external_flow_boundary_groups.id"],
            name="fk_observed_valuation_points_group",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_observed_valuation_points_scope_date",
        "observed_valuation_points",
        ["scope", "account_id", "observed_date"],
    )
    op.create_index(
        "ix_observed_valuation_points_flow",
        "observed_valuation_points",
        ["external_flow_id"],
    )
    op.create_index(
        "ix_observed_valuation_points_boundary_group",
        "observed_valuation_points",
        ["boundary_group_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    observed_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM observed_valuation_points")
    ).scalar_one()
    group_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM external_flow_boundary_groups")
    ).scalar_one()
    member_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM external_flow_boundary_group_members")
    ).scalar_one()
    if observed_count or group_count or member_count:
        raise RuntimeError(
            "cannot downgrade 0034_observed_valuation_boundaries while boundary evidence exists"
        )

    op.drop_index(
        "ix_observed_valuation_points_boundary_group",
        table_name="observed_valuation_points",
    )
    op.drop_index("ix_observed_valuation_points_flow", table_name="observed_valuation_points")
    op.drop_index(
        "ix_observed_valuation_points_scope_date",
        table_name="observed_valuation_points",
    )
    op.drop_table("observed_valuation_points")
    op.drop_index(
        "ix_external_flow_boundary_group_members_flow",
        table_name="external_flow_boundary_group_members",
    )
    op.drop_table("external_flow_boundary_group_members")
    op.drop_index(
        "ix_external_flow_boundary_groups_month_date",
        table_name="external_flow_boundary_groups",
    )
    op.drop_table("external_flow_boundary_groups")
