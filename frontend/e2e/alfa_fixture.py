"""Synthetic-only real API runtime for the Alfa native UI acceptance probe.

Uses existing canonical test builders; never configures a live provider.
Run through playwright.alfa.config.ts after the frontend production build.
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tests"))
import test_broker_baseline_apply as fixtures  # noqa: E402

from hermes_finance.main import create_app  # noqa: E402


def main():
    with TemporaryDirectory(prefix="hermes-alfa-synthetic-") as temporary:
        session, database = fixtures.session_for(Path(temporary))
        ids = fixtures._context(session)
        fixtures.confirm_mapping(
            session,
            provider=fixtures.ALFA_PRO_PROVIDER,
            subject_kind=fixtures.BrokerIdentitySubjectKind.ACCOUNT,
            provider_identity=fixtures.SYN_ACCOUNT,
            hermes_target_id=ids["account_id"],
        )
        fixtures.create_position_snapshot(
            session,
            reporting_month_id=ids["month_id"],
            account_id=ids["account_id"],
            instrument_id=ids["instrument_id"],
            quantity="9",
            average_cost_per_unit=fixtures.LOCAL_AVERAGE,
            market_price_per_unit=fixtures.LOCAL_MARKET,
            accrued_interest="0.00",
            price_date=fixtures.BASELINE_DATE,
            price_source=fixtures.PriceSource.MANUAL,
        )
        session.close()
        provider = fixtures.FakeSnapshotProvider(fixtures._snapshot())
        app = create_app(database, static_dir=ROOT / "frontend" / "dist", broker_snapshot_provider=provider)
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
        database.engine.dispose()


if __name__ == "__main__":
    main()
