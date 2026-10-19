"""Disposable zero-metadata source-intake provisional runtime; synthetic only."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import Response
from sqlalchemy import func, select


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend/tests"))
    from hermes_finance.main import create_app
    from hermes_finance.persistence import (
        Account,
        BrokerIdentityMapping,
        BrokerMonthApply,
        CashBalance,
        Instrument,
        MyBrokerImport,
        PositionSnapshot,
        ReportingMonth,
    )
    from hermes_finance.services import source_intake
    from test_statement_import_broker_statement_provisional import (
        FILENAME_APRIL,
        _free_database,
        provisional_xml,
    )

    with TemporaryDirectory(prefix="hermes-provisional-synthetic-") as temporary:
        database = _free_database(Path(temporary))
        raw = provisional_xml()
        with database.session_factory() as session:
            source_intake.save_intake(
                session,
                document=raw,
                filename=FILENAME_APRIL,
                request_id="e2e-unbound-provisional",
            )
        app = create_app(database, static_dir=root / "frontend/dist")

        @app.get("/api/synthetic-provisional-original")
        def source():
            return Response(raw, media_type="application/xml")

        @app.get("/api/synthetic-provisional-state")
        def state():
            models = (
                Account,
                Instrument,
                ReportingMonth,
                BrokerIdentityMapping,
                MyBrokerImport,
                BrokerMonthApply,
                PositionSnapshot,
                CashBalance,
            )
            with database.session_factory() as session:
                return {
                    model.__name__: session.scalar(
                        select(func.count()).select_from(model)
                    )
                    for model in models
                }

        app.router.routes.insert(0, app.router.routes.pop())
        app.router.routes.insert(0, app.router.routes.pop())
        try:
            uvicorn.run(app, host="127.0.0.1", port=18790, access_log=False)
        finally:
            database.engine.dispose()


if __name__ == "__main__":
    main()
