"""Add annual opening YTD gross context for salary tax.

Revision ID: 0021_salary_tax_year_contexts
Revises: 0020_legacy_migration_runs
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_salary_tax_year_contexts"
down_revision = "0020_legacy_migration_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "salary_tax_year_contexts",
        sa.Column("tax_year", sa.Integer(), primary_key=True),
        sa.Column("effective_from_month", sa.Integer(), nullable=False),
        sa.Column("opening_taxable_gross_kopecks", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "tax_year BETWEEN 1 AND 9999",
            name="ck_salary_tax_year_contexts_tax_year_range",
        ),
        sa.CheckConstraint(
            "effective_from_month BETWEEN 1 AND 12",
            name="ck_salary_tax_year_contexts_effective_month_range",
        ),
        sa.CheckConstraint(
            "opening_taxable_gross_kopecks >= 0",
            name="ck_salary_tax_year_contexts_opening_gross_nonnegative",
        ),
        sa.CheckConstraint(
            "effective_from_month != 1 OR opening_taxable_gross_kopecks = 0",
            name="ck_salary_tax_year_contexts_january_zero_opening",
        ),
    )


def downgrade() -> None:
    op.drop_table("salary_tax_year_contexts")
