"""Synthetic-only real API runtime for the #567 statement import acceptance probe.

Uses the existing canonical statement-import test builders and two synthetic
income-report PDFs (each deliberately spanning two reporting months); never
configures a live provider and never touches Owner data. Run through
playwright.statement.config.ts after the frontend production build.
"""

import sys
import tempfile
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import test_statement_import_apply as fixtures  # noqa: E402
from _statement_pdf import build_income_report_pdf  # noqa: E402

from hermes_finance.main import create_app  # noqa: E402
from hermes_finance.services.reporting_months import create_reporting_month  # noqa: E402

SYNTHETIC_DIR = "hermes-statement-synthetic"
NATIVE_PDF = "statement.pdf"
LEGACY_PDF = "statement-legacy.pdf"


def _january_row() -> dict[str, str]:
    return fixtures._row(record_date="15.01.2026", payment_date="20.01.2026")


def _february_coupon_row() -> dict[str, str]:
    return fixtures._row(
        payment_kind="погашение купона",
        isin=fixtures.SYN_ISIN_COUPON,
        quantity="10",
        per_unit="2,00",
        gross="20,00",
        tax="—",
        net="20,00",
        record_date="15.02.2026",
        payment_date="20.02.2026",
    )


def _january_coupon_row() -> dict[str, str]:
    return fixtures._row(
        payment_kind="погашение купона",
        isin=fixtures.SYN_ISIN_COUPON,
        quantity="10",
        per_unit="3,00",
        gross="30,00",
        tax="—",
        net="30,00",
        record_date="15.01.2026",
        payment_date="20.01.2026",
    )


def _february_dividend_row() -> dict[str, str]:
    return fixtures._row(record_date="15.02.2026", payment_date="20.02.2026")


def synthetic_pdf_path(name: str) -> Path:
    # Node's os.tmpdir() resolves the same TEMP/TMPDIR environment value.
    return Path(tempfile.gettempdir()) / SYNTHETIC_DIR / name


def main():
    directory = synthetic_pdf_path(NATIVE_PDF).parent
    directory.mkdir(parents=True, exist_ok=True)
    # One document per scenario: January 2026 + February 2026 in a single PDF.
    (directory / NATIVE_PDF).write_bytes(
        build_income_report_pdf([_january_row(), _february_coupon_row()])
    )
    (directory / LEGACY_PDF).write_bytes(
        build_income_report_pdf([_january_coupon_row(), _february_dividend_row()])
    )

    with TemporaryDirectory(prefix="hermes-statement-synthetic-") as temporary:
        session, database = fixtures.session_for(Path(temporary))
        fixtures.build_env(session, extra_isins=(fixtures.SYN_ISIN_COUPON,))
        create_reporting_month(session, year=2026, month=2, snapshot_date=date(2026, 2, 28))
        session.commit()
        session.close()
        app = create_app(database, static_dir=ROOT / "frontend" / "dist")
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
        database.engine.dispose()


if __name__ == "__main__":
    main()
