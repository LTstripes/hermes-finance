"""Empty permanent Money ownership links; no source or financial backfill."""

import sqlalchemy as sa
from alembic import op

revision = "0058_broker_money_ownership"
down_revision = "0057_broker_month_batch"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "broker_money_occurrence_owners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("mybroker_imports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("row_fingerprint", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "investment_cash_flow_id",
            sa.Integer(),
            sa.ForeignKey("investment_cash_flows.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "historical_owner_flow_id",
            sa.String(64),
            sa.ForeignKey("historical_owner_flows.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "accepted_request_id",
            sa.String(64),
            sa.ForeignKey("broker_month_applies.request_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint("import_id", "section", "ordinal", name="uq_broker_money_occurrence"),
        sa.CheckConstraint("section = 'money' AND ordinal >= 0", name="ck_broker_money_occurrence"),
        sa.CheckConstraint("length(row_fingerprint) = 64", name="ck_broker_money_fingerprint"),
        sa.CheckConstraint(
            "(role = 'coupon' AND investment_cash_flow_id IS NOT NULL AND historical_owner_flow_id IS NULL) OR (role = 'account_funding' AND historical_owner_flow_id IS NOT NULL AND investment_cash_flow_id IS NULL)",
            name="ck_broker_money_target",
        ),
    )


def downgrade():
    connection = op.get_bind()
    if (
        connection.execute(sa.text("SELECT COUNT(*) FROM broker_money_occurrence_owners")).scalar()
        or connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM broker_month_applies WHERE "
                "json_extract(projection_json, '$.contract_version') "
                "IN ('broker_money_v1', 'broker_money_dependency_v1')"
            )
        ).scalar()
    ):
        raise RuntimeError("cannot downgrade permanent Money ownership or evidence")
    op.drop_table("broker_money_occurrence_owners")
