"""Source-backed disposable runtime for exact instrument EOD observations."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from sqlalchemy import select

from hermes_finance.main import create_app
from hermes_finance.persistence import Instrument
from hermes_finance.services.accounts import create_account


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend" / "tests"))
    from test_instrument_eod_observations_service import add_stock_dividend, make_pair
    from test_statement_import_mybroker import ISIN, database

    with TemporaryDirectory(prefix="hermes-instrument-eod-synthetic-") as temporary:
        generator = database.__wrapped__(Path(temporary))
        db = next(generator)
        _, bond, intent, originals = make_pair(db)
        add_stock_dividend(db, bond, intent, originals)
        with db.session_factory() as session:
            stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
            stock.is_active = False
            session.commit()
            create_account(session, name="Synthetic empty EOD account", account_type="iis")
        try:
            uvicorn.run(
                create_app(db, static_dir=root / "frontend" / "dist"),
                host="127.0.0.1",
                port=int(os.environ.get("HERMES_EOD_TEST_PORT", "18860")),
            )
        finally:
            generator.close()


if __name__ == "__main__":
    main()
