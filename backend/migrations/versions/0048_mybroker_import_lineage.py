"""MyBroker S1 normalized source lineage, without financial backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0048_mybroker_import_lineage"
down_revision = "0047_class_endpoint_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mybroker_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("covered_from", sa.Date(), nullable=False),
        sa.Column("covered_to", sa.Date(), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("normalized_json", sa.Text(), nullable=False),
        sa.Column("mappings_json", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_sha256", name="uq_mybroker_import_document"),
        sa.CheckConstraint("length(document_sha256) = 64", name="ck_mybroker_import_hash"),
        sa.CheckConstraint("covered_to >= covered_from", name="ck_mybroker_import_range"),
        sa.CheckConstraint("length(confirmation_digest) = 64", name="ck_mybroker_confirmation"),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM mybroker_imports LIMIT 1")).first():
        raise RuntimeError("cannot discard MyBroker import lineage")
    op.drop_table("mybroker_imports")
