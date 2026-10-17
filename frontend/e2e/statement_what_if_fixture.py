"""Disposable synthetic WHAT-IF runtime; original/DB never come from an Owner profile."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import Response


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend/tests"))
    from hermes_finance.main import create_app
    from test_statement_import_broker_statement_what_if import incoming_source
    from test_statement_import_mybroker import database as fixture

    with TemporaryDirectory(prefix="hermes-what-if-synthetic-") as temporary:
        seed = fixture.__wrapped__(Path(temporary))
        database = next(seed)
        _, raw, _ = incoming_source(database)
        app = create_app(database, static_dir=root / "frontend/dist")

        @app.get("/api/synthetic-what-if-original")
        def source():
            return Response(raw, media_type="application/xml")

        app.router.routes.insert(0, app.router.routes.pop())
        uvicorn.run(app, host="127.0.0.1", port=18789, access_log=False)
        seed.close()


if __name__ == "__main__":
    main()
