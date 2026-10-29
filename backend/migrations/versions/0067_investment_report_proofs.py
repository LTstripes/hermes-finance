"""Typed investment-report proof profile on the existing source proof host."""

import sqlalchemy as sa
from alembic import op

from hermes_finance.source_return_proof_schema import DEPENDENCIES, install_sql_guards

revision = "0067_investment_report_proofs"
down_revision = "0066_actual_payout_links"
branch_labels = None
depends_on = None


def _constraint(expression, *, scoped):
    highwater = (
        op.get_bind()
        .execute(sa.text("SELECT seq FROM sqlite_sequence WHERE name='source_return_proofs'"))
        .scalar()
        or 0
    )
    for operation in ("update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS source_return_proofs_no_{operation}")
    with op.batch_alter_table(
        "source_return_proofs", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.drop_constraint("ck_source_return_proof_version", type_="check")
        batch.create_check_constraint("ck_source_return_proof_version", expression)
    op.get_bind().execute(
        sa.text("UPDATE sqlite_sequence SET seq=max(seq,:seq) WHERE name='source_return_proofs'"),
        {"seq": highwater},
    )
    for table in DEPENDENCIES:
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS return_proof_{table}_{operation}")
    install_sql_guards(op.get_bind(), scoped=scoped)


def upgrade():
    _constraint(
        "proof_version IN ('source_return_custody_v1','source_return_investment_v1')", scoped=True
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM source_return_proofs WHERE proof_version='source_return_investment_v1' LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("cannot downgrade populated investment report proof history")
    _constraint("proof_version = 'source_return_custody_v1'", scoped=False)
