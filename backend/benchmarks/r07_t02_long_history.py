"""Reproducible synthetic long-history benchmark for R07-T02.

The benchmark creates an isolated SQLite database in a temporary directory.
It never reads application settings, ``.env`` files, ``data/finance.db`` or
any other runtime input.  The seed is deliberately fixed so that the row
shape and endpoint workload are comparable between runs.

Run from ``backend``::

    uv run python benchmarks/r07_t02_long_history.py --years 1 5 10 20

The reported timings are local observations, not performance guarantees.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter_ns

from fastapi.testclient import TestClient
from sqlalchemy import event

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    AppSettings,
    Base,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    Goal,
    IncomeEntry,
    Instrument,
    InvestmentCashFlow,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    TaxBracket,
)

START_YEAR = 2000
REPEATS = 5
WARMUPS = 1
FORECAST_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class SeedResult:
    latest_month_id: int
    latest_period: tuple[int, int]
    row_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class Timing:
    median_ms: float
    p95_ms: float
    queries: int
    response_bytes: int


class QueryCounter:
    def __init__(self, database: Database) -> None:
        self.count = 0
        self._database = database

    def __enter__(self) -> "QueryCounter":
        event.listen(self._database.engine, "before_cursor_execute", self._before_execute)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(self._database.engine, "before_cursor_execute", self._before_execute)

    def _before_execute(
        self,
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        self.count += 1


def _month_at(index: int) -> tuple[int, int]:
    return START_YEAR + index // 12, index % 12 + 1


def _period_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _seed(database: Database, years: int) -> SeedResult:
    months_count = years * 12
    session = database.session_factory()
    try:
        accounts = [
            Account(name="Synthetic Broker A", account_type="brokerage", external_code="SYN-A"),
            Account(name="Synthetic Broker B", account_type="brokerage", external_code="SYN-B"),
            Account(name="Synthetic Deposit", account_type="deposit", external_code="SYN-D"),
            Account(name="Synthetic Savings", account_type="savings", external_code="SYN-S"),
            Account(name="Synthetic Cash", account_type="cash", external_code="SYN-C"),
        ]
        instruments = [
            Instrument(
                name=f"Synthetic {kind} {index}",
                instrument_type=kind,
                isin=f"SYNTH{index:07d}",
                ticker=f"SYN{index:02d}",
            )
            for index, kind in enumerate(
                ("stock", "stock", "bond", "bond", "fund", "currency", "gold", "other"),
                start=1,
            )
        ]
        session.add_all(accounts + instruments)
        session.flush()

        session.add_all(
            [
                AppSettings(
                    id=1,
                    base_currency="RUB",
                    locale="ru-RU",
                    timezone="Europe/Moscow",
                    passive_income_goal_kopecks=10_000_000,
                    formula_version="v1",
                    passive_income_history_start_month=None,
                ),
                Goal(
                    name="Synthetic passive income goal",
                    goal_type="passive_income",
                    target_value_kopecks=10_000_000,
                    target_date=None,
                    is_active=True,
                    is_main=True,
                    calculation_mode="monthly_net_passive_income",
                    notes=None,
                ),
                TaxBracket(
                    year=START_YEAR + years - 1,
                    threshold_from_kopecks=0,
                    threshold_to_kopecks=None,
                    rate_bps=1300,
                ),
            ]
        )

        months: list[ReportingMonth] = []
        for index in range(months_count):
            year, month = _month_at(index)
            period_start = date(year, month, 1)
            months.append(
                ReportingMonth(
                    year=year,
                    month=month,
                    period_start=period_start,
                    period_end=_period_end(year, month),
                    snapshot_date=_period_end(year, month),
                    status="closed",
                    source="manual",
                )
            )
        session.add_all(months)
        session.flush()

        positions: list[PositionSnapshot] = []
        deposits: list[DepositSnapshot] = []
        cash_balances: list[CashBalance] = []
        incomes: list[IncomeEntry] = []
        flows: list[InvestmentCashFlow] = []
        expected: list[ExpectedCashFlow] = []
        expenses: list[ExpenseEntry] = []
        debts: list[Debt] = []
        properties: list[PropertySnapshot] = []

        broker_a, broker_b, deposit_account, savings_account, cash_account = accounts
        for index, month_row in enumerate(months):
            year, month = _month_at(index)
            period_start = month_row.period_start
            period_end = month_row.period_end
            price = 100_000 + index * 125
            for account in (broker_a, broker_b):
                for instrument_index, instrument in enumerate(instruments, start=1):
                    quantity = 10 + instrument_index
                    cost = quantity * 90_000
                    market = quantity * (price + instrument_index * 1_000)
                    positions.append(
                        PositionSnapshot(
                            reporting_month_id=month_row.id,
                            account_id=account.id,
                            instrument_id=instrument.id,
                            quantity=quantity,
                            average_cost_per_unit_kopecks=90_000,
                            market_price_per_unit_kopecks=price + instrument_index * 1_000,
                            accrued_interest_kopecks=0,
                            market_value_kopecks=market,
                            cost_basis_kopecks=cost,
                            unrealized_result_kopecks=market - cost,
                            price_date=period_end,
                            price_source="manual",
                            manual_adjustment=False,
                        )
                    )

            deposits.extend(
                [
                    DepositSnapshot(
                        reporting_month_id=month_row.id,
                        account_id=deposit_account.id,
                        name="Synthetic fixed deposit",
                        deposit_type="deposit",
                        balance_kopecks=5_000_000 + index * 10_000,
                        annual_rate_basis_points=1_200,
                        expected_monthly_interest_kopecks=50_000 + index * 100,
                        actual_interest_received_kopecks=45_000 + index * 100,
                    ),
                    DepositSnapshot(
                        reporting_month_id=month_row.id,
                        account_id=savings_account.id,
                        name="Synthetic savings",
                        deposit_type="savings",
                        balance_kopecks=2_000_000 + index * 5_000,
                        annual_rate_basis_points=800,
                        expected_monthly_interest_kopecks=13_333 + index * 33,
                        actual_interest_received_kopecks=12_000 + index * 30,
                    ),
                ]
            )
            cash_balances.append(
                CashBalance(
                    reporting_month_id=month_row.id,
                    name="Synthetic cash",
                    amount_kopecks=1_000_000 + index * 2_000,
                    currency="RUB",
                    include_in_capital=True,
                )
            )
            incomes.append(
                IncomeEntry(
                    reporting_month_id=month_row.id,
                    income_type="bonus",
                    name="Synthetic annualized bonus",
                    gross_amount_kopecks=120_000,
                    tax_amount_kopecks=0,
                    net_amount_kopecks=120_000,
                    received_at=period_end,
                    is_recurring=False,
                    include_in_cash_flow=True,
                    include_in_passive_income=False,
                )
            )
            for flow_index, (flow_type, instrument_index) in enumerate(
                (("coupon", 3), ("dividend", 1), ("interest", 5), ("realized_profit", 2)),
                start=1,
            ):
                gross = 10_000 + index * 25 + flow_index * 100
                tax = gross // 10
                flows.append(
                    InvestmentCashFlow(
                        reporting_month_id=month_row.id,
                        account_id=broker_a.id,
                        instrument_id=instruments[instrument_index - 1].id,
                        flow_type=flow_type,
                        event_date=period_start + timedelta(days=flow_index),
                        gross_amount_kopecks=gross,
                        tax_amount_kopecks=tax,
                        commission_amount_kopecks=0,
                        net_amount_kopecks=gross - tax,
                        currency="RUB",
                        source="synthetic_benchmark",
                    )
                )
                expected.append(
                    ExpectedCashFlow(
                        reporting_month_id=month_row.id,
                        account_id=broker_a.id,
                        instrument_id=instruments[instrument_index - 1].id,
                        flow_type="redemption" if flow_type == "realized_profit" else flow_type,
                        expected_date=period_end + timedelta(days=15 + flow_index),
                        gross_amount_kopecks=gross,
                        expected_tax_amount_kopecks=tax,
                        expected_net_amount_kopecks=gross - tax,
                        currency="RUB",
                        source="synthetic_benchmark",
                        source_as_of_date=period_end,
                        forecast_version=FORECAST_VERSION,
                        is_confirmed=False,
                        is_approximate=False,
                    )
                )
            expenses.append(
                ExpenseEntry(
                    reporting_month_id=month_row.id,
                    category="Synthetic mandatory expense",
                    amount_kopecks=80_000,
                    expense_type="mandatory",
                    is_recurring=True,
                )
            )
            debts.append(
                Debt(
                    reporting_month_id=month_row.id,
                    debt_type="credit_card",
                    name="Synthetic credit card",
                    current_balance_kopecks=250_000,
                    include_in_liquid_capital=True,
                )
            )
            properties.append(
                PropertySnapshot(
                    reporting_month_id=month_row.id,
                    name="Synthetic property",
                    estimated_value_kopecks=20_000_000,
                    mortgage_balance_kopecks=8_000_000,
                    monthly_payment_kopecks=100_000,
                )
            )

        session.add_all(
            positions
            + deposits
            + cash_balances
            + incomes
            + flows
            + expected
            + expenses
            + debts
            + properties
        )
        session.commit()

        counts = Counter(
            {
                "reporting_months": len(months),
                "accounts": len(accounts),
                "instruments": len(instruments),
                "position_snapshots": len(positions),
                "deposit_snapshots": len(deposits),
                "cash_balances": len(cash_balances),
                "income_entries": len(incomes),
                "investment_cash_flows": len(flows),
                "expected_cash_flows": len(expected),
                "expense_entries": len(expenses),
                "debts": len(debts),
                "property_snapshots": len(properties),
            }
        )
        latest = months[-1]
        return SeedResult(
            latest_month_id=latest.id,
            latest_period=(latest.year, latest.month),
            row_counts=dict(counts),
        )
    finally:
        session.close()


def _assert_response(response: object, expected_status: int = 200) -> bytes:
    status_code = getattr(response, "status_code")
    content = getattr(response, "content")
    if status_code != expected_status:
        raise RuntimeError(f"benchmark request failed: status={status_code} body={content[:500]!r}")
    return content


def _measure(
    database: Database,
    operation: Callable[[], bytes],
    *,
    repeats: int,
    warmups: int = WARMUPS,
) -> Timing:
    for _ in range(warmups):
        operation()

    durations: list[float] = []
    query_counts: list[int] = []
    response_sizes: list[int] = []
    for _ in range(repeats):
        with QueryCounter(database) as counter:
            started = perf_counter_ns()
            content = operation()
            elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        durations.append(elapsed_ms)
        query_counts.append(counter.count)
        response_sizes.append(len(content))

    ordered = sorted(durations)
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return Timing(
        median_ms=statistics.median(durations),
        p95_ms=ordered[p95_index],
        queries=max(query_counts),
        response_bytes=max(response_sizes),
    )


def _run_case(years: int, repeats: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="hermes-r07-t02-") as temp_dir:
        database = create_database(Path(temp_dir) / "synthetic.sqlite3")
        Base.metadata.create_all(database.engine)
        seed = _seed(database, years)
        application = create_app(database)
        with TestClient(application) as client:
            latest_id = seed.latest_month_id
            latest_year, latest_month = seed.latest_period

            def dashboard() -> bytes:
                return _assert_response(client.get(f"/api/months/{latest_id}/dashboard"))

            def analytics() -> bytes:
                return _assert_response(client.get("/api/analytics/capital-composition"))

            def markdown_export() -> bytes:
                return _assert_response(client.post(f"/api/months/{latest_id}/export/markdown"))

            def json_export() -> bytes:
                return _assert_response(client.post(f"/api/months/{latest_id}/export/json"))

            lifecycle_number = 0

            def lifecycle() -> bytes:
                nonlocal lifecycle_number
                lifecycle_number += 1
                target_year = latest_year + 1 + lifecycle_number // 12
                target_month = lifecycle_number % 12 + 1
                snapshot = date(target_year, target_month, 28)
                cloned = _assert_response(
                    client.post(
                        f"/api/months/{latest_id}/clone",
                        json={
                            "year": target_year,
                            "month": target_month,
                            "snapshot_date": snapshot.isoformat(),
                        },
                    ),
                    expected_status=201,
                )
                cloned_id = json.loads(cloned)["id"]
                _assert_response(client.post(f"/api/months/{cloned_id}/close"))
                return _assert_response(client.post(f"/api/months/{cloned_id}/reopen"))

            backup = _assert_response(client.post("/api/backups"), expected_status=201)
            if not backup:
                raise RuntimeError("synthetic backup was unexpectedly empty")

            timings = {
                "dashboard_load": _measure(database, dashboard, repeats=repeats),
                "analytics_capital_composition": _measure(database, analytics, repeats=repeats),
                "markdown_export": _measure(database, markdown_export, repeats=repeats),
                "json_export": _measure(database, json_export, repeats=repeats),
                "month_clone_close_reopen": _measure(database, lifecycle, repeats=repeats),
                "backup_listing": _measure(
                    database,
                    lambda: _assert_response(client.get("/api/backups")),
                    repeats=repeats,
                ),
            }

        database.engine.dispose()

    return {
        "years": years,
        "months": years * 12,
        "rows": seed.row_counts,
        "timings": {
            operation: {
                "median_ms": round(timing.median_ms, 3),
                "p95_ms": round(timing.p95_ms, 3),
                "sql_queries": timing.queries,
                "response_bytes": timing.response_bytes,
            }
            for operation, timing in timings.items()
        },
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[1, 5, 10, 20])
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args(argv)
    if not args.years or any(years < 1 or years > 20 for years in args.years):
        parser.error("--years values must be between 1 and 20")
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    print(json.dumps([_run_case(years, args.repeats) for years in args.years], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
