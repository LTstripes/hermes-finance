"""Allow auditable retract of applied statement events.

Revision ID: 0029_statement_event_retract
Revises: 0028_applied_statement_events

Minimal M06-04 hotfix:
- current events gain an active/retracted status
- retracted events keep append-only revision history
- investment_cash_flow_id becomes nullable so a statement-created
  payout can be removed without deleting audit rows
- unique natural identity applies only to active events so the same
  statement row can be re-imported after retract

Existing 0.6.1 active rows remain active; historical revisions are
copied unchanged. No PDF/network/provider calls.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_statement_event_retract"
down_revision = "0028_applied_statement_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("applied_statement_event_revisions", "applied_statement_event_revisions_old")
    op.rename_table("applied_statement_events", "applied_statement_events_old")
    op.drop_index(
        "ix_applied_statement_event_revisions_event_id",
        table_name="applied_statement_event_revisions_old",
    )
    op.drop_index("ix_applied_statement_events_account", table_name="applied_statement_events_old")

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
        sa.Column("investment_cash_flow_id", sa.Integer(), nullable=True),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("link_mode", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('active', 'retracted')",
            name="ck_applied_statement_events_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND investment_cash_flow_id IS NOT NULL "
            "AND retracted_at IS NULL) OR "
            "(status = 'retracted' AND investment_cash_flow_id IS NULL "
            "AND retracted_at IS NOT NULL)",
            name="ck_applied_statement_events_retract_state",
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
            "investment_cash_flow_id",
            name="uq_applied_statement_events_cash_flow",
        ),
    )
    op.create_index(
        "ix_applied_statement_events_account",
        "applied_statement_events",
        ["account_id"],
    )
    op.create_index(
        "uq_applied_statement_events_active_identity",
        "applied_statement_events",
        ["provider", "natural_identity"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
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
            "revision_kind IN ('apply', 'revise', 'link_existing', 'retract')",
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

    op.execute(
        sa.text(
            """
            INSERT INTO applied_statement_events (
                id, provider, account_id, instrument_id, event_kind, isin,
                record_date, natural_identity, material_fingerprint,
                investment_cash_flow_id, document_sha256, link_mode, status,
                retracted_at, created_at, updated_at
            )
            SELECT
                id, provider, account_id, instrument_id, event_kind, isin,
                record_date, natural_identity, material_fingerprint,
                investment_cash_flow_id, document_sha256, link_mode, 'active',
                NULL, created_at, updated_at
            FROM applied_statement_events_old
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO applied_statement_event_revisions (
                id, applied_statement_event_id, revision_kind, document_sha256,
                natural_identity, material_fingerprint, account_id, instrument_id,
                event_kind, isin, record_date, event_date, quantity, per_unit,
                gross_amount_kopecks, gross_currency, tax_available,
                tax_amount_kopecks, tax_rate, net_amount_kopecks, net_currency,
                applied_at
            )
            SELECT
                id, applied_statement_event_id, revision_kind, document_sha256,
                natural_identity, material_fingerprint, account_id, instrument_id,
                event_kind, isin, record_date, event_date, quantity, per_unit,
                gross_amount_kopecks, gross_currency, tax_available,
                tax_amount_kopecks, tax_rate, net_amount_kopecks, net_currency,
                applied_at
            FROM applied_statement_event_revisions_old
            """
        )
    )

    op.drop_table("applied_statement_event_revisions_old")
    op.drop_table("applied_statement_events_old")


def downgrade() -> None:
    connection = op.get_bind()
    retracted = connection.execute(
        sa.text("SELECT COUNT(*) FROM applied_statement_events WHERE status = 'retracted'")
    ).scalar()
    if retracted:
        raise RuntimeError(
            "cannot downgrade 0029_statement_event_retract while retracted statement events exist"
        )

    op.rename_table("applied_statement_event_revisions", "applied_statement_event_revisions_new")
    op.rename_table("applied_statement_events", "applied_statement_events_new")
    op.drop_index(
        "ix_applied_statement_event_revisions_event_id",
        table_name="applied_statement_event_revisions_new",
    )
    op.drop_index("ix_applied_statement_events_account", table_name="applied_statement_events_new")
    op.drop_index(
        "uq_applied_statement_events_active_identity",
        table_name="applied_statement_events_new",
    )

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

    op.execute(
        sa.text(
            """
            INSERT INTO applied_statement_events (
                id, provider, account_id, instrument_id, event_kind, isin,
                record_date, natural_identity, material_fingerprint,
                investment_cash_flow_id, document_sha256, link_mode,
                created_at, updated_at
            )
            SELECT
                id, provider, account_id, instrument_id, event_kind, isin,
                record_date, natural_identity, material_fingerprint,
                investment_cash_flow_id, document_sha256, link_mode,
                created_at, updated_at
            FROM applied_statement_events_new
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO applied_statement_event_revisions (
                id, applied_statement_event_id, revision_kind, document_sha256,
                natural_identity, material_fingerprint, account_id, instrument_id,
                event_kind, isin, record_date, event_date, quantity, per_unit,
                gross_amount_kopecks, gross_currency, tax_available,
                tax_amount_kopecks, tax_rate, net_amount_kopecks, net_currency,
                applied_at
            )
            SELECT
                id, applied_statement_event_id, revision_kind, document_sha256,
                natural_identity, material_fingerprint, account_id, instrument_id,
                event_kind, isin, record_date, event_date, quantity, per_unit,
                gross_amount_kopecks, gross_currency, tax_available,
                tax_amount_kopecks, tax_rate, net_amount_kopecks, net_currency,
                applied_at
            FROM applied_statement_event_revisions_new
            """
        )
    )

    op.drop_table("applied_statement_event_revisions_new")
    op.drop_table("applied_statement_events_new")
