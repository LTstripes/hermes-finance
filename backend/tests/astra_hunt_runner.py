"""Offline replay of synthetic XML through production readers, without finance Apply."""

import json
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory

from test_statement_import_broker_statement_provisional import _finite_tables, _free_database
from test_statement_import_mybroker import ACCOUNT

from hermes_finance.persistence import Base
from hermes_finance.services import source_intake
from hermes_finance.services.portfolio_twrr import portfolio_twrr_for_interval
from hermes_finance.services.portfolio_xirr import portfolio_xirr_for_interval
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_monthly_returns import read_monthly_returns
from hermes_finance.statement_import.mybroker import MyBrokerError, parse_mybroker

ROOT = Path(__file__).resolve().parents[2] / "tests/fixtures/astra_hunt"
CASES = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def replay(database, case):
    document = (ROOT / (case["case"] + ".xml")).read_bytes()
    try:
        parsed = parse_mybroker(document, case["filename"])
    except MyBrokerError as error:
        return {
            "case": case["case"],
            "parser_error": str(error),
            "calculation": "not_run_parser_rejected",
        }
    with database.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=document, filename=case["filename"], request_id=case["case"]
        )
    before = snapshot(database)
    with database.session_factory() as session:
        view = source_intake.read_intake(session, ack["intake_id"])
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        reattached = read_monthly_returns(
            session,
            source_account=ACCOUNT,
            originals={ack["intake_id"]: (document, case["filename"])},
        )
        instruments = read_instrument_returns(session, source_account=ACCOUNT)
        interval = dict(
            start_date=date.fromisoformat(parsed["covered_from"]) - timedelta(days=1),
            end_date=date.fromisoformat(parsed["covered_to"]),
        )
        exact_xirr = portfolio_xirr_for_interval(session, **interval)
        exact_twrr = portfolio_twrr_for_interval(session, **interval)
    assert snapshot(database) == before
    assert all(count == 0 for count in _finite_tables(database).values())
    return {
        "case": case["case"],
        "parser": {
            key: parsed[key]
            for key in ("syntax_blockers", "endpoint_blockers", "endpoint_conflicts")
        },
        "row_counts": {key: len(parsed[key]) for key in ("positions", "money", "trades")},
        "classifications": [row["classification"] for row in view["money_classifications"]],
        "monthly": asdict(monthly),
        "reattached_period": asdict(reattached.period),
        "instruments": asdict(instruments),
        "exact_xirr": asdict(exact_xirr),
        "exact_twrr": asdict(exact_twrr),
    }


def snapshot(database):
    with database.engine.connect() as connection:
        return {
            table.name: connection.exec_driver_sql(
                f'SELECT * FROM "{table.name}" ORDER BY rowid'
            ).fetchall()
            for table in Base.metadata.sorted_tables
        }


def replay_gap(database):
    for case in (CASES[0], CASES[-1]):
        with database.session_factory() as session:
            source_intake.save_intake(
                session,
                document=(ROOT / (case["case"] + ".xml")).read_bytes(),
                filename=case["filename"],
                request_id=case["case"],
            )
    before = snapshot(database)
    with database.session_factory() as session:
        result = read_monthly_returns(session, source_account=ACCOUNT)
    assert snapshot(database) == before
    assert all(count == 0 for count in _finite_tables(database).values())
    return {"case": "01_plus_25_missing_may", "monthly": asdict(result)}


def main():
    results = []
    scratch_parent = Path(__file__).resolve().parents[1] / ".pytest_cache"
    scratch_parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="synthetic-astra-hunt-", dir=scratch_parent) as scratch:
        for case in CASES:
            directory = Path(scratch) / case["case"]
            directory.mkdir()
            database = _free_database(directory)
            try:
                result = replay(database, case)
                results.append(result)
                if "parser_error" in result:
                    print(case["case"], result["parser_error"])
                else:
                    period = result["monthly"]["period"]
                    print(
                        case["case"],
                        result["classifications"],
                        "XIRR=",
                        period["xirr_period_return"],
                        "Dietz=",
                        period["chained_return"],
                        "gaps=",
                        sorted({g["code"] for g in result["monthly"]["gaps"]}),
                    )
            finally:
                database.engine.dispose()
        directory = Path(scratch) / "coverage-gap"
        directory.mkdir()
        database = _free_database(directory)
        try:
            results.append(replay_gap(database))
        finally:
            database.engine.dispose()
    (ROOT / "results.json").write_text(
        json.dumps(results, default=json_value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
