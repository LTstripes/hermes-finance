"""Persist statement period separately from operation replacement range."""

import json
import re
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0070_spending_screen"
down_revision = "0069_spending_diary"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("spending_uploads", sa.Column("period_from", sa.Date(), nullable=True))
    op.add_column("spending_uploads", sa.Column("period_to", sa.Date(), nullable=True))
    op.add_column(
        "spending_uploads", sa.Column("account_name", sa.Text(), server_default="", nullable=False)
    )
    bind = op.get_bind()
    for upload in (
        bind.execute(sa.text("SELECT id,filename FROM spending_uploads WHERE source='alfa_csv'"))
        .mappings()
        .all()
    ):
        match = re.search(
            r"Statement (\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})", upload["filename"], re.I
        )
        if match:
            try:
                start, end = (
                    datetime.strptime(value, "%d.%m.%Y").date() for value in match.groups()
                )
            except ValueError:
                start = end = None
            if start is not None and end is not None and start <= end:
                bind.execute(
                    sa.text(
                        "UPDATE spending_uploads SET period_from=:start,period_to=:end WHERE id=:id"
                    ),
                    dict(start=start, end=end, id=upload["id"]),
                )
        raw = bind.execute(
            sa.text("SELECT raw_json FROM spending_operations WHERE upload_id=:id LIMIT 1"),
            dict(id=upload["id"]),
        ).scalar()
        if raw:
            name = json.loads(raw).get("accountName", "")
            bind.execute(
                sa.text("UPDATE spending_uploads SET account_name=:name WHERE id=:id"),
                dict(name=name, id=upload["id"]),
            )
    # Correct only the two obsolete T1 classifications, retaining every owner decision.
    bind.execute(
        sa.text(
            "UPDATE spending_operations SET kind='purchase',reason=CASE WHEN category='Без категории' THEN 'uncategorized' ELSE NULL END WHERE source='alfa_csv' AND reason='unknown_cardless'"
        )
    )
    for row in (
        bind.execute(
            sa.text(
                "SELECT id,category FROM spending_operations WHERE source='alfa_csv' AND amount_kopecks>0 AND currency='RUR' AND status IN ('','Выполнен','В обработке')"
            )
        )
        .mappings()
        .all()
    ):
        if " ".join(row["category"].split()).upper() == "НАКОПЛЕНИЯ":
            bind.execute(
                sa.text("UPDATE spending_operations SET kind='transfer',reason=NULL WHERE id=:id"),
                dict(id=row["id"]),
            )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM spending_uploads WHERE period_from IS NOT NULL OR account_name != '' LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("cannot discard statement coverage metadata")
    op.drop_column("spending_uploads", "account_name")
    op.drop_column("spending_uploads", "period_to")
    op.drop_column("spending_uploads", "period_from")
