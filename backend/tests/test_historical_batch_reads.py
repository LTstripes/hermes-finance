"""Correctness locks for batched historical read assemblers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from sqlalchemy import select

from hermes_finance.database import create_database
from hermes_finance.persistence import Base, ReportingMonth
from hermes_finance.services.asset_allocation import (
    asset_allocation_for_month,
    asset_allocation_for_months,
)
from hermes_finance.services.liquid_capital import (
    liquid_capital_for_month,
    liquid_capital_for_months,
)
from hermes_finance.services.passive_income import (
    passive_income_for_month,
    passive_income_for_months,
)

_BENCHMARK_PATH = Path(__file__).parents[1] / "benchmarks" / "r07_t02_long_history.py"
_SPEC = importlib.util.spec_from_file_location("r07_t02_long_history", _BENCHMARK_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_BENCHMARK = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _BENCHMARK
_SPEC.loader.exec_module(_BENCHMARK)
_seed = _BENCHMARK._seed


def test_batched_historical_results_match_single_month_assemblers(tmp_path: Path) -> None:
    database = create_database(tmp_path / "historical-batch.sqlite3")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        _seed(database, 2)
        months = list(
            session.scalars(
                select(ReportingMonth).order_by(ReportingMonth.year, ReportingMonth.month)
            )
        )
        month_ids = [month.id for month in months]

        single_liquid = {
            month_id: liquid_capital_for_month(session, month_id) for month_id in month_ids
        }
        single_passive = {
            month_id: passive_income_for_month(session, month_id) for month_id in month_ids
        }
        batched_liquid = liquid_capital_for_months(session, month_ids)
        batched_passive = passive_income_for_months(session, month_ids)
        assert batched_liquid == single_liquid
        assert batched_passive == single_passive

        single_allocations = {
            month_id: asset_allocation_for_month(session, month_id, single_liquid[month_id])
            for month_id in month_ids
        }
        batched_allocations = asset_allocation_for_months(session, month_ids, batched_liquid)
        assert batched_allocations == single_allocations
    finally:
        session.close()
        database.engine.dispose()
