"""Measure the redesigned screens on reproducible, disposable synthetic data.

Run from the repository root with the locked backend environment::

    backend/.venv/Scripts/python backend/benchmarks/issue1067_screen_reads.py \
        --output /path/to/measurements.json --payloads /path/to/responses.json

Only in-process HTTP GETs against a temporary SQLite database are timed. The
first request is process-cold for that endpoint; subsequent requests are warm,
but OS page caches are not cleared. No browser, network, user DB or provider is
involved. Data comes entirely from the existing synthetic test fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
import traceback
from collections import Counter
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import event, select

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "tests"))
sys.path.insert(0, str(BACKEND / "benchmarks"))

# This benchmark must not inherit an Owner runtime's settings or .env file.
for name in tuple(os.environ):
    if name.upper().startswith("HERMES_"):
        del os.environ[name]
from hermes_finance.settings import Settings  # noqa: E402

Settings.model_config["env_file"] = None

import r07_t02_long_history as history  # noqa: E402
from test_source_instrument_returns_service import save  # noqa: E402
from test_source_monthly_returns_service import snapshot  # noqa: E402
from test_statement_import_broker_statement_provisional import provisional_xml  # noqa: E402
from test_statement_import_mybroker import ACCOUNT  # noqa: E402

from hermes_finance.database import create_database  # noqa: E402
from hermes_finance.main import create_app  # noqa: E402
from hermes_finance.persistence import Account, Base, ExpectedCashFlow, Instrument  # noqa: E402
from hermes_finance.services.database_admission import database_admission  # noqa: E402
from hermes_finance.services.reporting_months import create_reporting_month  # noqa: E402
from hermes_finance.services.source_intake import save_intake  # noqa: E402


def seed(database):
    history.START_YEAR = 2030
    closed = history._seed(database, 1)
    for month in range(1, 11):
        save(database, month=month)
        end = history._period_end(2030, month).day
        raw = (
            provisional_xml(candidate_count=0)
            .decode()
            .replace("2030-04-", f"2030-{month:02d}-")
            .replace(".04.2030", f".{month:02d}.2030")
            .replace(ACCOUNT, "7654321-000")
            .encode()
        )
        with database.session_factory() as session:
            save_intake(
                session,
                document=raw,
                filename=f"Брокерский 7654321 (01.{month:02d}.30-{end}.{month:02d}.30).xml",
                request_id=f"benchmark-second-{month}",
            )
    with database.session_factory() as session:
        draft = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
        month_id = draft.id
        account = session.scalar(select(Account).where(Account.external_code == "SYN-A"))
        instruments = session.scalars(select(Instrument).order_by(Instrument.id)).all()
        assert account is not None and len(instruments) == 8
        session.add_all(
            ExpectedCashFlow(
                reporting_month_id=month_id,
                account_id=account.id,
                instrument_id=instrument.id,
                flow_type="coupon",
                expected_date=date(2031, 2, 1) + timedelta(days=30 * offset),
                gross_amount_kopecks=10000,
                expected_tax_amount_kopecks=1000,
                expected_net_amount_kopecks=9000,
                currency="RUB",
                source="synthetic_benchmark",
                source_as_of_date=date(2031, 1, 31),
                forecast_version="v1",
                is_confirmed=False,
                is_approximate=False,
            )
            for instrument in instruments
            for offset in range(8)
        )
        session.commit()
    return closed.latest_month_id, month_id


def run(
    repeats: int,
    *,
    only: set[str] | None = None,
    trace: bool = False,
    database_dir: Path | None = None,
    reuse: bool = False,
):
    location = (
        nullcontext(str(database_dir))
        if database_dir
        else tempfile.TemporaryDirectory(prefix="hermes-1067-synthetic-")
    )
    with location as tmp:
        root = Path(tmp)
        marker = root / "synthetic-fixture.json"
        db_path = root / "synthetic.sqlite3"
        if reuse:
            if not marker.is_file() or not db_path.is_file():
                raise RuntimeError("refusing to reuse an unmarked or missing synthetic database")
            fixture = json.loads(marker.read_text(encoding="utf-8"))
            if fixture.get("format") != "hermes-1067-synthetic-v1":
                raise RuntimeError("synthetic database marker is incompatible")
        else:
            root.mkdir(parents=True, exist_ok=True)
            if any(root.iterdir()):
                raise RuntimeError("refusing to create a fixture in a nonempty directory")
        database = create_database(db_path)
        try:
            if reuse:
                closed_id, draft_id = fixture["closed_id"], fixture["draft_id"]
            else:
                print("Creating synthetic schema", file=sys.stderr, flush=True)
                Base.metadata.create_all(database.engine)
                print("Seeding synthetic history and statements", file=sys.stderr, flush=True)
                closed_id, draft_id = seed(database)
                marker.write_text(
                    json.dumps(
                        {
                            "format": "hermes-1067-synthetic-v1",
                            "closed_id": closed_id,
                            "draft_id": draft_id,
                        }
                    ),
                    encoding="utf-8",
                )
            print("Reading initial synthetic database snapshot", file=sys.stderr, flush=True)
            before = snapshot(database)
            app = create_app(database)
            # Eliminate process-only confirmation epochs from response comparison;
            # this fixed identity exists only in the disposable benchmark app.
            from hermes_finance.services import source_intake

            source_intake.PROCESS_EPOCH = "synthetic-benchmark"
            database.maintenance.form_incarnation = "synthetic-benchmark"
            app.state.quote_preview_clock = lambda: date(2031, 2, 1)
            app.state.freshness_generated_at = lambda: datetime(2031, 2, 1, tzinfo=UTC)
            paths = {
                "months": "/api/months",
                "working_status": "/api/months/working-status",
                "home_comparison": "/api/analytics/closed-report-comparison?include_capital_change=false",
                "home_composition": "/api/analytics/capital-composition",
                "home_passive": f"/api/analytics/passive-income?reporting_month_id={closed_id}",
                "home_goals": f"/api/goals/summary?reporting_month_id={closed_id}",
                "month_workflow_checklist": f"/api/months/{draft_id}/close-workflow?include_checklist=true",
                "month_workflow_plain": f"/api/months/{draft_id}/close-workflow",
                "month_dashboard": f"/api/months/{draft_id}/dashboard?include_capital_change=false",
                "month_summary": f"/api/months/{draft_id}/summary?include_capital_change=false",
                "returns": "/api/returns/overall?include_instrument_summaries=true",
                "instrument": "/api/returns/instrument-card?isin=RU000A000000",
                "source_intakes": "/api/broker-months/intakes?include_unbound=true",
                "month_broker_sources": f"/api/months/{draft_id}/broker-sources",
            }
            measurements, payloads = {}, {}
            print("Starting in-process HTTP client", file=sys.stderr, flush=True)
            # Match the stock CLI's server-lifetime admission, including its
            # nesting contract for connections opened on HTTP worker threads.
            with database_admission(database.database_path), TestClient(app) as client:
                for name, path in paths.items():
                    if only and name not in only:
                        continue
                    times, query_counts, sizes = [], [], []
                    statements = Counter()
                    callsites = Counter()

                    def count(_conn, _cursor, statement, _params, _context, _many):
                        statements[" ".join(statement.split())] += 1
                        if trace:
                            frames = [
                                f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                                for frame in traceback.extract_stack()
                                if "hermes_finance" in frame.filename
                            ]
                            callsites[" > ".join(frames[-7:])] += 1

                    for iteration in range(repeats + 1):
                        statements.clear()
                        event.listen(database.engine, "before_cursor_execute", count)
                        try:
                            started = perf_counter()
                            response = client.get(path)
                            elapsed = (perf_counter() - started) * 1000
                        finally:
                            event.remove(database.engine, "before_cursor_execute", count)
                        if response.status_code != 200:
                            raise RuntimeError(
                                f"{name}: {response.status_code} {response.text[:500]}"
                            )
                        body = response.json()
                        if iteration == 0:
                            payloads[name] = body
                        elif body != payloads[name]:
                            raise AssertionError(f"{name}: repeated response changed")
                        times.append(elapsed)
                        query_counts.append(sum(statements.values()))
                        sizes.append(len(response.content))
                    measurements[name] = {
                        "path": path,
                        "cold_ms": round(times[0], 1),
                        "warm_median_ms": round(statistics.median(times[1:]), 1),
                        "warm_samples_ms": [round(value, 1) for value in times[1:]],
                        "sql_queries": query_counts,
                        "response_bytes": sizes[0],
                        "response_sha256": hashlib.sha256(response.content).hexdigest(),
                        "repeated_sql": [
                            {"count": count, "sql": sql[:220]}
                            for sql, count in statements.most_common(8)
                            if count > 1
                        ],
                    }
                    if trace:
                        measurements[name]["callsites"] = callsites.most_common(30)
                    print(
                        f"{name}: cold={times[0]:.1f} ms, "
                        f"warm median={statistics.median(times[1:]):.1f} ms, "
                        f"SQL={query_counts[-1]}",
                        file=sys.stderr,
                        flush=True,
                    )
            assert snapshot(database) == before, "GET requests changed synthetic database rows"
            return {
                "fixture": "12 closed months + 1 draft, 20 synthetic statement intakes / 2 source accounts, 64 draft expected payouts",
                "method": "in-process TestClient; first request then repeat requests; local SQLite, warm OS cache",
                "repeats": repeats,
                "database_unchanged": True,
                "measurements": measurements,
            }, payloads
        finally:
            database.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--payloads", type=Path, required=True)
    parser.add_argument("--only", nargs="+", help="limit the endpoint names")
    parser.add_argument("--trace", action="store_true", help="record SQL call stacks (slower)")
    parser.add_argument("--database-dir", type=Path, help="dedicated synthetic fixture directory")
    parser.add_argument("--reuse", action="store_true", help="reuse a marked synthetic fixture")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.reuse and not args.database_dir:
        parser.error("--reuse requires --database-dir")
    measurements, payloads = run(
        args.repeats,
        only=set(args.only or ()),
        trace=args.trace,
        database_dir=args.database_dir,
        reuse=args.reuse,
    )
    args.output.write_text(json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
    args.payloads.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
