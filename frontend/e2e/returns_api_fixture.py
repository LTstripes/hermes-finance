"""Disposable two-account HTTP fixture for Returns. Only GET /api/returns is exposed."""

import os
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

import uvicorn
from fastapi.responses import JSONResponse


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend/tests"))
    from hermes_finance.main import create_app
    from hermes_finance.persistence import Account, Instrument
    from hermes_finance.services.reporting_months import create_reporting_month
    from hermes_finance.services.source_intake import save_intake
    from hermes_finance.statement_import.mybroker import NS
    from test_source_monthly_returns_service import snapshot
    from test_statement_import_broker_statement_provisional import (
        _free_database,
        provisional_xml,
    )
    from test_statement_import_mybroker import ACCOUNT, ISIN

    with TemporaryDirectory(prefix="returns-synthetic-") as temporary:
        db = _free_database(Path(temporary))
        with db.session_factory() as session:
            session.add(
                Instrument(
                    isin=ISIN,
                    name="Учебная акция из каталога",
                    instrument_type="stock",
                    is_active=False,
                )
            )
            session.add(Account(name="Учебный депозит", account_type="deposit"))
            closed = create_reporting_month(
                session, year=2030, month=4, snapshot_date=date(2030, 4, 30)
            )
            closed.status = "closed"
            session.commit()
            create_reporting_month(
                session, year=2030, month=5, snapshot_date=date(2030, 5, 31)
            )
        for alias, closing in (("1234567", "1100"), ("7654321", "900")):
            raw = provisional_xml(candidate_count=0)
            tree = ET.fromstring(raw)
            pos = tree.find(".//m:Details[@ISIN1]", NS)
            pos.attrib.update(
                active_name=ISIN,
                income_rest="10",
                real_rest="10",
                forward_rest="10",
                income_volume="1000",
                real_volume=closing,
            )
            trades = tree.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS)
            for trade in list(trades):
                trades.remove(trade)
            raw = ET.tostring(tree, encoding="utf-8").replace(
                ACCOUNT.encode(), f"{alias}-000".encode()
            )
            with db.session_factory() as session:
                save_intake(
                    session,
                    document=raw,
                    filename=f"Брокерский {alias} (01.04.30-30.04.30).xml",
                    request_id=f"synthetic-{alias}",
                )
                june = ET.fromstring(raw)
                june.find(".//m:Details[@ISIN1]", NS).attrib.update(
                    income_volume="1200",
                    real_volume="1180" if alias == "1234567" else "1220",
                )
                june_raw = (
                    ET.tostring(june, encoding="utf-8")
                    .decode()
                    .replace("2030-04-", "2030-06-")
                    .replace(".04.2030", ".06.2030")
                    .encode()
                )
                save_intake(
                    session,
                    document=june_raw,
                    filename=f"Брокерский {alias} (01.06.30-30.06.30).xml",
                    request_id=f"synthetic-june-{alias}",
                )
        before = snapshot(db)
        app = create_app(database=db, static_dir=root / "frontend/dist")

        @app.middleware("http")
        async def read_only(request, call_next):
            if request.method != "GET" or (
                request.url.path.startswith("/api/")
                and not request.url.path.startswith("/api/returns/")
            ):
                return JSONResponse({"error": "synthetic_read_only"}, status_code=403)
            response = await call_next(request)
            assert snapshot(db) == before
            return response

        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=int(os.environ.get("HERMES_RETURNS_TEST_PORT", "18963")),
                access_log=False,
            )
        finally:
            assert snapshot(db) == before
            db.engine.dispose()


if __name__ == "__main__":
    main()
