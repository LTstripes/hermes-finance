"""Disposable source-backed stock WHAT-IF; no Owner data or normal runtime."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from hermes_finance.main import create_app
from hermes_finance.services.accounts import create_account


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend" / "tests"))
    from test_instrument_what_if_service import setup_stock
    from test_statement_import_mybroker import database

    with TemporaryDirectory(prefix="hermes-stock-what-if-synthetic-") as temporary:
        generator = database.__wrapped__(Path(temporary))
        db = next(generator)
        setup_stock(db)
        with db.session_factory() as session:
            create_account(
                session, name="Synthetic empty scenario account", account_type="iis"
            )
        try:
            uvicorn.run(
                create_app(db, static_dir=root / "frontend" / "dist"),
                host="127.0.0.1",
                port=int(os.environ.get("HERMES_WHAT_IF_TEST_PORT", "18865")),
            )
        finally:
            generator.close()


if __name__ == "__main__":
    main()
