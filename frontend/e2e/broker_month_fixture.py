"""Synthetic disposable source-first broker-month runtime; never a real profile."""

import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import Response
from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.reporting_months import create_reporting_month


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend" / "tests"))
    from test_statement_import_mybroker_endpoints import (
        broker_month_alias_xml,
        money_batch_xml,
        money_coupon_pdf,
        trade_money_xml,
    )

    with TemporaryDirectory(prefix="hermes-broker-month-synthetic-") as temporary:
        database = create_database(Path(temporary) / "finance.db")
        Base.metadata.create_all(database.engine)
        with database.session_factory() as session:
            create_account(session, name="Synthetic broker", account_type="brokerage")
            create_account(
                session, name="Unrelated synthetic deposit", account_type="deposit"
            )
            create_instrument(
                session,
                name="Synthetic stock",
                instrument_type="stock",
                isin="RU000A000000",
                currency="RUB",
            )
            create_instrument(
                session,
                name="Synthetic bond",
                instrument_type="bond",
                isin="RU000A000001",
                currency="RUB",
            )
            for number, end in ((1, 31), (2, 28), (3, 31), (4, 30)):
                create_reporting_month(
                    session,
                    year=2030,
                    month=number,
                    snapshot_date=date(2030, number, end),
                )
        app = create_app(database, static_dir=root / "frontend" / "dist")

        @app.get("/api/synthetic-broker-source/{kind}")
        def source(kind: str):
            if kind == "trade-money":
                xml = (
                    trade_money_xml()
                    .replace(b".01.2030", b".04.2030")
                    .replace(b"2030-01-", b"2030-04-")
                    .replace(b".01.30", b".04.30")
                    .replace(b"10000000001", b"10000000004")
                    .replace(b"2000000001", b"2000000004")
                )
                return Response(xml, media_type="application/xml")
            if kind == "money-pdf":
                return Response(money_coupon_pdf(month=3), media_type="application/pdf")
            if kind == "money":
                xml = (
                    money_batch_xml(nkd=True)
                    .replace(b".01.2030", b".03.2030")
                    .replace(b"2030-01-", b"2030-03-")
                    .replace(b".01.30", b".03.30")
                )
                return Response(xml, media_type="application/xml")
            xml = broker_month_alias_xml(bond=True, unsupported=kind == "partial")
            if kind == "partial":
                xml = (
                    xml.replace(b".01.2030", b".02.2030")
                    .replace(b"2030-01-", b"2030-02-")
                    .replace(b"10000000001", b"10000000002")
                    .replace(b"2000000001", b"2000000002")
                )
            return Response(xml, media_type="application/xml")

        # Test-only XML endpoint must precede the app's SPA catch-all.
        app.router.routes.insert(0, app.router.routes.pop())
        uvicorn.run(app, host="127.0.0.1", port=18773, access_log=False)
        database.engine.dispose()


if __name__ == "__main__":
    main()
