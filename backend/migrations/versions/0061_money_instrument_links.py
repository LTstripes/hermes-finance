"""Nullable provisional payout identities; legacy rows remain unprocessed."""

import sqlalchemy as sa
from alembic import op

revision = "0061_money_instrument_links"
down_revision = "0060_source_money_classifications"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("source_intake_money_classifications") as batch:
        batch.add_column(sa.Column("security_reg_number", sa.String(32), nullable=True))
        batch.add_column(sa.Column("security_issuer", sa.Text(), nullable=True))
        batch.add_column(sa.Column("instrument_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("instrument_link_status", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_source_money_instrument",
            "instruments",
            ["instrument_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_source_money_instrument_link_status",
            "instrument_link_status IS NULL OR instrument_link_status IN "
            "('linked','unresolved_no_match','unresolved_ambiguous','not_parsed','kind_mismatch','not_applicable')",
        )
        batch.create_check_constraint(
            "ck_source_money_instrument_link",
            "(instrument_link_status IS NOT NULL AND instrument_link_status = 'linked' AND instrument_id IS NOT NULL "
            "AND security_reg_number IS NOT NULL AND security_issuer IS NOT NULL) OR "
            "(COALESCE(instrument_link_status, '') != 'linked' AND instrument_id IS NULL)",
        )


def downgrade():
    with op.batch_alter_table("source_intake_money_classifications") as batch:
        batch.drop_constraint("ck_source_money_instrument_link", type_="check")
        batch.drop_constraint("ck_source_money_instrument_link_status", type_="check")
        batch.drop_constraint("fk_source_money_instrument", type_="foreignkey")
        for name in (
            "instrument_link_status",
            "instrument_id",
            "security_issuer",
            "security_reg_number",
        ):
            batch.drop_column(name)
