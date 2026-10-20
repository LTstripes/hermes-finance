"""Persist provisional money classifications at upload; no legacy backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0060_source_money_classifications"
down_revision = "0059_source_intake"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_intake_money_classifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "intake_id",
            sa.Integer(),
            sa.ForeignKey("source_intake_originals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            sa.Integer(),
            sa.ForeignKey("source_intake_observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_reference", sa.String(128), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger()),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("intake_id", "source_reference", name="uq_source_money_reference"),
        sa.UniqueConstraint("observation_id", name="uq_source_money_observation"),
        sa.CheckConstraint(
            "classification IN ('external_deposit','external_withdrawal','coupon','dividend',"
            "'fee','tax','trade_settlement','internal_transfer','unknown')",
            name="ck_source_money_classification",
        ),
        sa.CheckConstraint(
            "origin IN ('default_rule','user_choice')", name="ck_source_money_origin"
        ),
        sa.CheckConstraint("status IN ('assumed','confirmed')", name="ck_source_money_status"),
        sa.CheckConstraint(
            "(origin = 'default_rule' AND status = 'assumed') OR "
            "(origin = 'user_choice' AND status = 'confirmed')",
            name="ck_source_money_choice_status",
        ),
    )


def downgrade():
    op.drop_table("source_intake_money_classifications")
