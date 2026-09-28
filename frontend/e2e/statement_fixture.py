"""Synthetic-only real API runtime for the #567 statement import acceptance probe.

Uses the existing canonical statement-import test builders and a synthetic
income-report PDF; never configures a live provider and never touches Owner
data. Run through playwright.statement.config.ts after the frontend
production build.
"""

import os
import sys
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import test_statement_import_apply as fixtures  # noqa: E402
from _statement_pdf import build_income_report_pdf  # noqa: E402

from hermes_finance.main import create_app  # noqa: E402

SYNTHETIC_DIR = "hermes-statement-synthetic"
SYNTHETIC_NAME = "statement.pdf"


def synthetic_pdf_path() -> Path:
    # Node's os.tmpdir() resolves the same TEMP/TMPDR environment value.
    return Path(tempfile.gettempdir()) / SYNTHETIC_DIR / SYNTHETIC_NAME


def main():
    pdf_path = synthetic_pdf_path()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(build_income_report_pdf())
    if not os.path.exists(pdf_path):
        raise RuntimeError("synthetic statement PDF was not written")

    with TemporaryDirectory(prefix="hermes-statement-synthetic-") as temporary:
        session, database = fixtures.session_for(Path(temporary))
        fixtures.build_env(session)
        session.commit()
        session.close()
        app = create_app(database, static_dir=ROOT / "frontend" / "dist")
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
        database.engine.dispose()


if __name__ == "__main__":
    main()
