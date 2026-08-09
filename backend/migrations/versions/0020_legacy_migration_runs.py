"""Add durable idempotency marker for transactional legacy imports (F10).

Revision ID: 0020_legacy_migration_runs
Revises: 0019_position_deposit_updated_at
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_legacy_migration_runs"
down_revision = "0019_position_deposit_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_migration_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("policy", sa.String(length=32), nullable=False),
        sa.Column("backup_id", sa.String(length=128), nullable=False),
        sa.Column("month_count", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("source_sha256", name="uq_legacy_migration_runs_source_sha256"),
        sa.CheckConstraint("month_count > 0", name="ck_legacy_migration_runs_month_count_positive"),
    )


def downgrade() -> None:
    op.drop_table("legacy_migration_runs")
