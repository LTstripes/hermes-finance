"""Persist explicit v1 scope-membership evidence for external flows.

Revision ID: 0031_external_flow_scope_membership
Revises: 0030_external_flow_persistence

The current ``accounts.include_in_returns`` flag is not effective-dated and
must not be applied retroactively to historical boundary flows.  Existing
R08-01A rows therefore receive the conservative ``unknown`` value.  No
legacy-flow backfill or inference is performed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_external_flow_scope_membership"
down_revision = "0030_external_flow_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("external_flows") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope_membership",
                sa.String(length=24),
                server_default=sa.text("'unknown'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_external_flows_scope_membership",
            "scope_membership IN ('unknown', 'stable_in_scope', 'stable_out_of_scope')",
        )


def downgrade() -> None:
    connection = op.get_bind()
    asserted_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM external_flows WHERE scope_membership != 'unknown'")
    ).scalar_one()
    if asserted_count:
        raise RuntimeError(
            "cannot downgrade 0031_external_flow_scope_membership while owner scope evidence exists"
        )

    with op.batch_alter_table("external_flows") as batch_op:
        batch_op.drop_constraint("ck_external_flows_scope_membership", type_="check")
        batch_op.drop_column("scope_membership")
