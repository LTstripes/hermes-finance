"""Preserve 0065 facts while adding explicit actual payout provenance."""

from alembic import op

from hermes_finance.actual_payout_schema import migrate

revision = "0066_actual_payout_links"
down_revision = "0065_source_return_proofs"
branch_labels = None
depends_on = None


def upgrade():
    migrate(op.get_bind(), upgrade=True)


def downgrade():
    migrate(op.get_bind(), upgrade=False)
