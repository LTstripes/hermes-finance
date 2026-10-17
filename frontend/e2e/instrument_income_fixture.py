"""Disposable, source-backed synthetic runtime for known-payout desktop checks."""

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
    from test_instrument_cash_income_service import (
        dividend_pdf,
        pdf_apply,
        pdf_preview,
        selection_from_row,
        setup,
    )
    from test_statement_import_mybroker import ISIN, database
    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide

    with TemporaryDirectory(prefix="hermes-known-payouts-synthetic-") as temporary:
        generator = database.__wrapped__(Path(temporary))
        db = next(generator)
        _, intent, bond, _, originals = setup(db)
        with db.session_factory() as session:
            pdf = dividend_pdf()
            row = pdf_preview(session, pdf, intent.account_id).rows[0]
            assert pdf_apply(session, pdf, intent.account_id, (selection_from_row(row),)).success
            reviewed = _money_decide(
                session, intent, originals, bond, funding=False, operation="reaffirm"
            )
            _money_apply(session, reviewed, originals, "synthetic-payout-reaffirm")
            stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
            # No runtime holdings endpoint is consulted by the drill-down.
            stock.is_active = False
            session.commit()
            # Catalogue edit retires Money: explicit existing reaffirm restores it.
            reviewed = _money_decide(
                session, intent, originals, bond, funding=False, operation="reaffirm"
            )
            _money_apply(session, reviewed, originals, "synthetic-payout-final")
            create_account(session, name="Synthetic empty payout account", account_type="iis")
        app = create_app(db, static_dir=root / "frontend" / "dist")
        try:
            uvicorn.run(
                app, host="127.0.0.1", port=int(os.environ.get("HERMES_INCOME_TEST_PORT", "18858"))
            )
        finally:
            generator.close()


if __name__ == "__main__":
    main()
