"""Append-only source custody-month proof; no reparse or economic backfill."""

import sqlalchemy as sa
from alembic import op

from hermes_finance.source_return_proof_schema import DEPENDENCIES, install_sql_guards

revision = "0065_source_return_proofs"
down_revision = "0064_month_template_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_return_proofs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_account", sa.String(256), nullable=False),
        sa.Column("native_account", sa.String(256), nullable=False),
        sa.Column("request_id", sa.String(64), unique=True, nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("proof_version", sa.String(32), nullable=False),
        sa.Column("dependency_digest", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "proof_version = 'source_return_custody_v1'", name="ck_source_return_proof_version"
        ),
        sa.CheckConstraint(
            "length(dependency_digest) = 64", name="ck_source_return_proof_dependency"
        ),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "source_return_proof_dependencies",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(64), nullable=False),
        sqlite_autoincrement=True,
    )
    install_sql_guards(op.get_bind())


def downgrade():
    # Auxiliary retirement nonces have no authority without a proof. Proof rows
    # are append-only: empty proves none ever depended on this auxiliary state.
    # Any proof history (even stale) forbids downgrade before the first DDL.
    if op.get_bind().execute(sa.text("SELECT 1 FROM source_return_proofs LIMIT 1")).first():
        raise RuntimeError("cannot downgrade populated source return proof history")
    for table in DEPENDENCIES:
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS return_proof_{table}_{operation}")
    op.drop_table("source_return_proofs")
    op.drop_table("source_return_proof_dependencies")
