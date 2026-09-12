"""Persist transfer-specific canonical reconciliation evidence.

Revision ID: 0039_transfer_reconciliation_evidence
Revises: 0038_cash_boundary_coverage

The migration is additive and does not infer or backfill fee, tax, or FX
evidence from existing transactions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_transfer_reconciliation_evidence"
down_revision = "0038_cash_boundary_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_transfer_reconciliation_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transfer_link_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("evidence_reference", sa.String(length=128), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('internal_fee', 'internal_commission', 'internal_tax', "
            "'fx_conversion_spread')",
            name="ck_external_transfer_reconciliation_evidence_kind",
        ),
        sa.CheckConstraint(
            "amount_kopecks >= 0",
            name="ck_external_transfer_reconciliation_evidence_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3",
            name="ck_external_transfer_reconciliation_evidence_currency_length",
        ),
        sa.CheckConstraint(
            "length(trim(source)) > 0",
            name="ck_external_transfer_reconciliation_evidence_source_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(evidence_reference)) > 0",
            name="ck_external_transfer_reconciliation_evidence_reference_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_link_id"],
            ["external_transfer_links.id"],
            name="fk_external_transfer_reconciliation_evidence_transfer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_reference",
            name="uq_external_transfer_reconciliation_evidence_reference",
        ),
    )
    op.create_index(
        "ix_external_transfer_reconciliation_evidence_transfer",
        "external_transfer_reconciliation_evidence",
        ["transfer_link_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM external_transfer_reconciliation_evidence")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "cannot downgrade 0039_transfer_reconciliation_evidence while evidence exists"
        )
    op.drop_index(
        "ix_external_transfer_reconciliation_evidence_transfer",
        table_name="external_transfer_reconciliation_evidence",
    )
    op.drop_table("external_transfer_reconciliation_evidence")
