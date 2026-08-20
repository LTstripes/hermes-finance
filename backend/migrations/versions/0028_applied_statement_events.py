"""Add applied statement event and append-only revision tables.

Revision ID: 0028_applied_statement_events
Revises: 0027_applied_provider_payouts

Additive R06-08 persistence only. Existing owner cash-flow rows are not
rewritten, no statement provenance is backfilled, and upgrade/downgrade
make zero provider/network/PDF calls.
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_applied_statement_events"
down_revision = "0027_applied_provider_payouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applied_statement_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("natural_identity", sa.String(length=256), nullable=False),
        sa.Column("material_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("investment_cash_flow_id", sa.Integer(), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("link_mode", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('alfa_depository_income_report')",
            name="ck_applied_statement_events_provider",
        ),
        sa.CheckConstraint(
            "event_kind IN ('dividend', 'coupon', 'redemption')",
            name="ck_applied_statement_events_event_kind",
        ),
        sa.CheckConstraint(
            "link_mode IN ('statement_created', 'linked_existing')",
            name="ck_applied_statement_events_link_mode",
        ),
        sa.CheckConstraint(
            "length(natural_identity) > 0",
            name="ck_applied_statement_events_identity_present",
        ),
        sa.CheckConstraint(
            "length(material_fingerprint) = 64",
            name="ck_applied_statement_events_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "length(document_sha256) = 64",
            name="ck_applied_statement_events_document_sha256",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["investment_cash_flow_id"],
            ["investment_cash_flows.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "natural_identity",
            name="uq_applied_statement_events_identity",
        ),
        sa.UniqueConstraint(
            "investment_cash_flow_id",
            name="uq_applied_statement_events_cash_flow",
        ),
    )
    op.create_index(
        "ix_applied_statement_events_account",
        "applied_statement_events",
        ["account_id"],
    )

    op.create_table(
        "applied_statement_event_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("applied_statement_event_id", sa.Integer(), nullable=False),
        sa.Column("revision_kind", sa.String(length=16), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("natural_identity", sa.String(length=256), nullable=False),
        sa.Column("material_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.String(length=64), nullable=False),
        sa.Column("per_unit", sa.String(length=64), nullable=False),
        sa.Column("gross_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("gross_currency", sa.String(length=3), nullable=False),
        sa.Column("tax_available", sa.Boolean(), nullable=False),
        sa.Column("tax_amount_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("tax_rate", sa.String(length=64), nullable=True),
        sa.Column("net_amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("net_currency", sa.String(length=3), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_kind IN ('apply', 'revise', 'link_existing')",
            name="ck_applied_statement_event_revisions_kind",
        ),
        sa.CheckConstraint(
            "event_kind IN ('dividend', 'coupon', 'redemption')",
            name="ck_applied_statement_event_revisions_event_kind",
        ),
        sa.CheckConstraint(
            "gross_currency = 'RUB'",
            name="ck_applied_statement_event_revisions_gross_currency_rub",
        ),
        sa.CheckConstraint(
            "net_currency = 'RUB'",
            name="ck_applied_statement_event_revisions_net_currency_rub",
        ),
        sa.CheckConstraint(
            "gross_amount_kopecks >= 0",
            name="ck_applied_statement_event_revisions_gross_nonnegative",
        ),
        sa.CheckConstraint(
            "net_amount_kopecks >= 0",
            name="ck_applied_statement_event_revisions_net_nonnegative",
        ),
        sa.CheckConstraint(
            "length(quantity) > 0",
            name="ck_applied_statement_event_revisions_quantity_present",
        ),
        sa.CheckConstraint(
            "length(per_unit) > 0",
            name="ck_applied_statement_event_revisions_per_unit_present",
        ),
        sa.CheckConstraint(
            "(tax_available = 0 AND tax_amount_kopecks IS NULL) OR "
            "(tax_available = 1 AND tax_amount_kopecks IS NOT NULL "
            "AND tax_amount_kopecks >= 0)",
            name="ck_applied_statement_event_revisions_tax_evidence",
        ),
        sa.CheckConstraint(
            "length(natural_identity) > 0",
            name="ck_applied_statement_event_revisions_identity_present",
        ),
        sa.CheckConstraint(
            "length(material_fingerprint) = 64",
            name="ck_applied_statement_event_revisions_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "length(document_sha256) = 64",
            name="ck_applied_statement_event_revisions_document_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["applied_statement_event_id"],
            ["applied_statement_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_applied_statement_event_revisions_event_id",
        "applied_statement_event_revisions",
        ["applied_statement_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_applied_statement_event_revisions_event_id",
        table_name="applied_statement_event_revisions",
    )
    op.drop_table("applied_statement_event_revisions")
    op.drop_index(
        "ix_applied_statement_events_account",
        table_name="applied_statement_events",
    )
    op.drop_table("applied_statement_events")
