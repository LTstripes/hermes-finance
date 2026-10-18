"""Durable zero-economic source observations and append-only review commands."""

import sqlalchemy as sa
from alembic import op

revision = "0059_source_intake"
down_revision = "0058_broker_money_ownership"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_intake_originals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("filename_digest", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("covered_from", sa.Date(), nullable=False),
        sa.Column("covered_to", sa.Date(), nullable=False),
        sa.Column("native_accounts_json", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_sha256", name="uq_source_intake_original"),
        sa.CheckConstraint(
            "length(document_sha256) = 64 AND byte_length > 0", name="ck_intake_original"
        ),
        sa.CheckConstraint("covered_to >= covered_from", name="ck_intake_period"),
    )
    op.create_table(
        "source_intake_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "original_id",
            sa.Integer(),
            sa.ForeignKey("source_intake_originals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("row_fingerprint", sa.String(64), nullable=False),
        sa.Column("row_class", sa.String(32), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "original_id", "generation", "section", "ordinal", name="uq_intake_occurrence"
        ),
        sa.CheckConstraint("generation > 0 AND ordinal >= 0", name="ck_intake_ordinal"),
        sa.CheckConstraint("length(row_fingerprint) = 64", name="ck_intake_fingerprint"),
    )
    op.create_table(
        "source_intake_revisions",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), unique=True, nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column(
            "original_id",
            sa.Integer(),
            sa.ForeignKey("source_intake_originals.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "reporting_month_id",
            sa.Integer(),
            sa.ForeignKey("reporting_months.id", ondelete="RESTRICT"),
        ),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="RESTRICT")),
        sa.Column(
            "expected_predecessor_seq",
            sa.Integer(),
            sa.ForeignKey("source_intake_revisions.seq", ondelete="RESTRICT"),
        ),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("contract_version = 'source_intake_v1'", name="ck_intake_contract"),
        sa.CheckConstraint(
            "operation IN ('manifest','decision','policy','finance_link','dependency')",
            name="ck_intake_operation",
        ),
        sa.CheckConstraint("length(confirmation_digest) = 64", name="ck_intake_confirmation"),
        sqlite_autoincrement=True,
    )
    from hermes_finance.services.source_intake import install_sql_guards

    install_sql_guards(op.get_bind())


def downgrade():
    connection = op.get_bind()
    for table in (
        "source_intake_revisions",
        "source_intake_observations",
        "source_intake_originals",
    ):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            raise RuntimeError("cannot downgrade populated source intake journal")
    for table in (
        "accounts",
        "instruments",
        "broker_identity_mappings",
        "position_snapshots",
        "cash_balances",
        "investment_cash_flows",
        "external_flows",
    ):
        for operation in ("insert", "update", "delete"):
            connection.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS intake_dependency_{table}_{operation}"
            )
    for table in (
        "source_intake_revisions",
        "source_intake_observations",
        "source_intake_originals",
    ):
        op.drop_table(table)
