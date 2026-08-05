"""Create the application settings singleton.

Revision ID: 0002_app_settings
Revises: 0001_empty_init
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_app_settings"
down_revision = "0001_empty_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    app_settings = op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "base_currency", sa.String(length=3), server_default=sa.text("'RUB'"), nullable=False
        ),
        sa.Column(
            "locale", sa.String(length=32), server_default=sa.text("'ru-RU'"), nullable=False
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Europe/Moscow'"),
            nullable=False,
        ),
        sa.Column(
            "passive_income_goal_kopecks",
            sa.BigInteger(),
            server_default=sa.text("10000000"),
            nullable=False,
        ),
        sa.Column(
            "formula_version", sa.String(length=32), server_default=sa.text("'v1'"), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_app_settings_singleton_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        app_settings,
        [
            {
                "id": 1,
                "base_currency": "RUB",
                "locale": "ru-RU",
                "timezone": "Europe/Moscow",
                "passive_income_goal_kopecks": 10_000_000,
                "formula_version": "v1",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("app_settings")
