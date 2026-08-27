"""Contract tests for the R07-T02 synthetic benchmark generator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.persistence import Base

_BENCHMARK_PATH = Path(__file__).parents[1] / "benchmarks" / "r07_t02_long_history.py"
_SPEC = importlib.util.spec_from_file_location("r07_t02_long_history", _BENCHMARK_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_BENCHMARK = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _BENCHMARK
_SPEC.loader.exec_module(_BENCHMARK)
_seed = _BENCHMARK._seed


def test_synthetic_seed_is_fixed_and_scales_by_month(tmp_path: Path) -> None:
    database = create_database(tmp_path / "synthetic-benchmark.sqlite3")
    Base.metadata.create_all(database.engine)
    try:
        result = _seed(database, 2)
        assert result.latest_period == (2001, 12)
        assert result.row_counts == {
            "reporting_months": 24,
            "accounts": 5,
            "instruments": 8,
            "position_snapshots": 384,
            "deposit_snapshots": 48,
            "cash_balances": 24,
            "income_entries": 24,
            "investment_cash_flows": 96,
            "expected_cash_flows": 96,
            "expense_entries": 24,
            "debts": 24,
            "property_snapshots": 24,
        }
    finally:
        database.engine.dispose()
