"""Empty owner-editable registration-number to ISIN crosswalk; no seeded identities."""

import sqlalchemy as sa
from alembic import op

revision = "0062_security_reg_isin_mappings"
down_revision = "0061_money_instrument_links"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "security_reg_isin_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reg_number", sa.String(32), nullable=False),
        sa.Column("isin", sa.String(12), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reg_number", name="uq_security_reg_isin_reg_number"),
        sa.CheckConstraint(
            "length(reg_number) BETWEEN 1 AND 32 AND reg_number = upper(trim(reg_number)) "
            "AND reg_number NOT GLOB '*[^A-Z0-9-]*'",
            name="ck_security_reg_isin_reg_number",
        ),
        sa.CheckConstraint(
            "length(isin) = 12 AND substr(isin,1,2) GLOB '[A-Z][A-Z]' "
            "AND substr(isin,3,9) NOT GLOB '*[^A-Z0-9]*' "
            "AND substr(isin,12,1) GLOB '[0-9]'",
            name="ck_security_reg_isin_isin",
        ),
    )


def downgrade():
    # Derived links/classifications and journal evidence remain untouched.
    op.drop_table("security_reg_isin_mappings")
