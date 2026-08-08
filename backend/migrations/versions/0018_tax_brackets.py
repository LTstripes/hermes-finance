"""Create tax_brackets configuration table for progressive НДФЛ.

Progressive tax scale in force since 2025 (ФЗ-176-ФЗ of 12.07.2024):
  up to 2 400 000 RUB inclusive  — 13%
  2 400 000 – 5 000 000         — 15%
  5 000 000 – 20 000 000        — 18%
  20 000 000 – 50 000 000       — 20%
  over 50 000 000               — 22%

Source: https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/

Revision ID: 0018_tax_brackets
Revises: 0017_comments
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_tax_brackets"
down_revision = "0017_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tax_brackets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("threshold_from_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("threshold_to_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.CheckConstraint("threshold_from_kopecks >= 0", name="ck_tax_brackets_from_nonnegative"),
        sa.CheckConstraint(
            "threshold_to_kopecks IS NULL OR threshold_to_kopecks > threshold_from_kopecks",
            name="ck_tax_brackets_to_after_from",
        ),
        sa.CheckConstraint("rate_bps >= 0", name="ck_tax_brackets_rate_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "threshold_from_kopecks", name="uq_tax_brackets_year_from"),
    )


def downgrade() -> None:
    op.drop_table("tax_brackets")
