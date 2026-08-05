"""Create the Alembic service baseline.

Revision ID: 0001_empty_init
Revises: None
"""

revision = "0001_empty_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Record the initial migration baseline without domain tables."""


def downgrade() -> None:
    """Return to a database without an Alembic revision."""
