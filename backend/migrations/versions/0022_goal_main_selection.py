"""Persist explicit main-goal selection and backfill legacy passive target.

Revision ID: 0022_goal_main_selection
Revises: 0021_salary_tax_year_contexts

Legacy compatibility rule:
- zero active passive-income goals: create one main goal from app settings;
- one active passive-income goal: mark that existing row as main;
- multiple active passive-income goals: fail closed and require explicit cleanup.
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_goal_main_selection"
down_revision = "0021_salary_tax_year_contexts"
branch_labels = None
depends_on = None


_AMBIGUOUS_LEGACY_GOALS_ERROR = (
    "R02-11 migration blocked: multiple active passive-income goals exist; "
    "choose exactly one main goal before retrying the migration"
)


def upgrade() -> None:
    connection = op.get_bind()
    active_passive_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM goals WHERE goal_type = 'passive_income' AND is_active = 1")
    ).scalar_one()
    if active_passive_count > 1:
        raise RuntimeError(_AMBIGUOUS_LEGACY_GOALS_ERROR)

    op.add_column(
        "goals",
        sa.Column("is_main", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    if active_passive_count == 0:
        op.execute(
            sa.text(
                "INSERT INTO goals "
                "(name, goal_type, target_value_kopecks, target_date, is_active, is_main, calculation_mode, notes) "
                "SELECT 'Пассивный доход в месяц', 'passive_income', "
                "passive_income_goal_kopecks, NULL, 1, 1, "
                "'monthly_net_passive_income', NULL "
                "FROM app_settings WHERE id = 1"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE goals SET is_main = 1 WHERE goal_type = 'passive_income' AND is_active = 1"
            )
        )
    op.create_index(
        "uq_goals_single_main",
        "goals",
        ["is_main"],
        unique=True,
        sqlite_where=sa.text("is_main = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_goals_single_main", table_name="goals")
    with op.batch_alter_table("goals") as batch_op:
        batch_op.drop_column("is_main")
