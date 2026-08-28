"""Add explicit external boundary flows and owner transfer links.

Revision ID: 0030_external_flow_persistence
Revises: 0029_statement_event_retract

R08-01A is additive.  Existing ``investment_cash_flows`` rows, including
``deposit`` and ``withdrawal`` rows, are intentionally not copied or
reclassified: their boundary meaning is not proven by the legacy schema.
The migration performs no provider, network, or owner-data inference.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_external_flow_persistence"
down_revision = "0029_statement_event_retract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_transfer_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transfer_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'unresolved'"),
            nullable=False,
        ),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('unresolved', 'resolved')",
            name="ck_external_transfer_links_status",
        ),
        sa.CheckConstraint(
            "length(trim(transfer_key)) > 0",
            name="ck_external_transfer_links_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_key", name="uq_external_transfer_links_key"),
    )

    op.create_table(
        "external_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporting_month_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("boundary_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'RUB'"),
            nullable=False,
        ),
        sa.Column("transfer_link_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('external_contribution', 'external_withdrawal')",
            name="ck_external_flows_kind",
        ),
        sa.CheckConstraint(
            "direction IN ('contribution', 'withdrawal')",
            name="ck_external_flows_direction",
        ),
        sa.CheckConstraint(
            "(kind = 'external_contribution' AND direction = 'contribution') OR "
            "(kind = 'external_withdrawal' AND direction = 'withdrawal')",
            name="ck_external_flows_kind_direction",
        ),
        sa.CheckConstraint(
            "boundary_amount_kopecks >= 0",
            name="ck_external_flows_boundary_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3",
            name="ck_external_flows_currency_length",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_month_id"], ["reporting_months.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["transfer_link_id"], ["external_transfer_links.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_external_flows_month", "external_flows", ["reporting_month_id"])
    op.create_index("ix_external_flows_account", "external_flows", ["account_id"])
    op.create_index("ix_external_flows_transfer_link", "external_flows", ["transfer_link_id"])


def downgrade() -> None:
    connection = op.get_bind()
    external_flow_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM external_flows")
    ).scalar_one()
    transfer_link_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM external_transfer_links")
    ).scalar_one()
    if external_flow_count or transfer_link_count:
        raise RuntimeError(
            "cannot downgrade 0030_external_flow_persistence while external-flow data exists"
        )

    op.drop_index("ix_external_flows_transfer_link", table_name="external_flows")
    op.drop_index("ix_external_flows_account", table_name="external_flows")
    op.drop_index("ix_external_flows_month", table_name="external_flows")
    op.drop_table("external_flows")
    op.drop_table("external_transfer_links")
