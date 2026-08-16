"""Refactor instrument market mappings to provider-neutral identity.

Revision ID: 0025_provider_neutral_market_identity
Revises: 0024_instrument_market_mappings

Existing MOEX rows are rewritten in-place without network calls:
provider stays unchanged, provider_instrument_id = old secid,
provider_venue_id = engine/market/boardid in canonical form.
Legacy instruments.moex_secid is never promoted.
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_provider_neutral_market_identity"
down_revision = "0024_instrument_market_mappings"
branch_labels = None
depends_on = None


def _encode_venue(engine: object, market: object, boardid: object) -> str:
    return f"{str(engine).strip().lower()}/{str(market).strip().lower()}/{str(boardid).strip().upper()}"


def _decode_venue(venue: object) -> tuple[str, str, str]:
    text = "" if venue is None else str(venue)
    parts = text.split("/")
    if len(parts) != 3 or any(not part.strip() for part in parts):
        raise ValueError(
            f"cannot downgrade mapping identity without a 3-part provider_venue_id (got {venue!r})"
        )
    return parts[0].strip().lower(), parts[1].strip().lower(), parts[2].strip().upper()


def upgrade() -> None:
    op.create_table(
        "instrument_market_mappings_new",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_instrument_id", sa.String(length=128), nullable=True),
        sa.Column("provider_venue_id", sa.String(length=96), nullable=True),
        sa.Column("excluded", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "("
            "(provider IS NULL AND provider_instrument_id IS NULL "
            "AND provider_venue_id IS NULL) "
            "OR "
            "(provider IS NOT NULL AND provider_instrument_id IS NOT NULL)"
            ")",
            name="ck_instrument_market_mappings_identity_atomic",
        ),
        sa.CheckConstraint(
            "excluded = 1 OR (provider IS NOT NULL AND provider_instrument_id IS NOT NULL)",
            name="ck_instrument_market_mappings_mapped_complete",
        ),
        sa.CheckConstraint(
            "excluded IN (0, 1)",
            name="ck_instrument_market_mappings_excluded_bool",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_instrument_market_mappings_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instrument_id"),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT instrument_id, provider, engine, market, boardid, secid, excluded, updated_at "
            "FROM instrument_market_mappings"
        )
    ).fetchall()
    insert = sa.text(
        "INSERT INTO instrument_market_mappings_new "
        "(instrument_id, provider, provider_instrument_id, provider_venue_id, excluded, updated_at) "
        "VALUES (:instrument_id, :provider, :provider_instrument_id, :provider_venue_id, "
        ":excluded, :updated_at)"
    )
    for row in rows:
        if row.provider is None:
            provider = None
            provider_instrument_id = None
            provider_venue_id = None
        else:
            provider = row.provider
            provider_instrument_id = str(row.secid).strip().upper()
            provider_venue_id = _encode_venue(row.engine, row.market, row.boardid)
        connection.execute(
            insert,
            {
                "instrument_id": row.instrument_id,
                "provider": provider,
                "provider_instrument_id": provider_instrument_id,
                "provider_venue_id": provider_venue_id,
                "excluded": row.excluded,
                "updated_at": row.updated_at,
            },
        )

    op.drop_table("instrument_market_mappings")
    op.rename_table("instrument_market_mappings_new", "instrument_market_mappings")


def downgrade() -> None:
    op.create_table(
        "instrument_market_mappings_old",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("engine", sa.String(length=32), nullable=True),
        sa.Column("market", sa.String(length=32), nullable=True),
        sa.Column("boardid", sa.String(length=32), nullable=True),
        sa.Column("secid", sa.String(length=32), nullable=True),
        sa.Column("excluded", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "("
            "(provider IS NULL AND engine IS NULL AND market IS NULL "
            "AND boardid IS NULL AND secid IS NULL) "
            "OR "
            "(provider IS NOT NULL AND engine IS NOT NULL AND market IS NOT NULL "
            "AND boardid IS NOT NULL AND secid IS NOT NULL)"
            ")",
            name="ck_instrument_market_mappings_identity_atomic",
        ),
        sa.CheckConstraint(
            "excluded = 1 OR ("
            "provider IS NOT NULL AND engine IS NOT NULL AND market IS NOT NULL "
            "AND boardid IS NOT NULL AND secid IS NOT NULL"
            ")",
            name="ck_instrument_market_mappings_mapped_complete",
        ),
        sa.CheckConstraint(
            "excluded IN (0, 1)",
            name="ck_instrument_market_mappings_excluded_bool",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_instrument_market_mappings_instrument_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instrument_id"),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT instrument_id, provider, provider_instrument_id, provider_venue_id, "
            "excluded, updated_at FROM instrument_market_mappings"
        )
    ).fetchall()
    insert = sa.text(
        "INSERT INTO instrument_market_mappings_old "
        "(instrument_id, provider, engine, market, boardid, secid, excluded, updated_at) "
        "VALUES (:instrument_id, :provider, :engine, :market, :boardid, :secid, "
        ":excluded, :updated_at)"
    )
    for row in rows:
        if row.provider is None:
            engine = market = boardid = secid = None
        else:
            if row.provider_venue_id is None:
                raise ValueError(
                    "cannot downgrade mapping identity without a 3-part provider_venue_id"
                )
            engine, market, boardid = _decode_venue(row.provider_venue_id)
            secid = str(row.provider_instrument_id).strip().upper()
        connection.execute(
            insert,
            {
                "instrument_id": row.instrument_id,
                "provider": row.provider,
                "engine": engine,
                "market": market,
                "boardid": boardid,
                "secid": secid,
                "excluded": row.excluded,
                "updated_at": row.updated_at,
            },
        )

    op.drop_table("instrument_market_mappings")
    op.rename_table("instrument_market_mappings_old", "instrument_market_mappings")
