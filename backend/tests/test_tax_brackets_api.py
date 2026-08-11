from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType, ReportingMonthStatus
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, ReportingMonth
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.salary import calculate_salary_tax


def _rule(lower: str, upper: str | None, rate_bps: int) -> dict[str, object]:
    return {
        "threshold_from": {"amount": lower, "currency": "RUB"},
        "threshold_to": ({"amount": upper, "currency": "RUB"} if upper is not None else None),
        "rate_bps": rate_bps,
    }


def _two_bracket_payload() -> dict[str, object]:
    return {
        "brackets": [
            _rule("0.00", "100000.00", 1000),
            _rule("100000.00", None, 2000),
        ]
    }


def test_tax_bracket_api_defaults_replace_and_salary_use(tmp_path: Path) -> None:
    database = create_database(tmp_path / "tax-brackets-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            default = client.get("/api/tax-brackets/2035")
            assert default.status_code == 200
            body = default.json()
            assert body["year"] == 2035
            assert body["effective_from"] == "2035-01-01"
            assert body["effective_to"] == "2035-12-31"
            assert body["source"] == "official_default"
            assert body["contract_version"] == "tax_brackets_year_v1"
            assert body["mutable"] is True
            assert body["closed_months"] == []
            assert len(body["brackets"]) == 5

            replaced = client.put("/api/tax-brackets/2035", json=_two_bracket_payload())
            assert replaced.status_code == 200
            replaced_body = replaced.json()
            assert replaced_body["source"] == "manual_configuration"
            assert replaced_body["brackets"] == _two_bracket_payload()["brackets"]

        with database.session_factory() as session:
            month = create_reporting_month(
                session, year=2035, month=1, snapshot_date=date(2035, 1, 31)
            )
            create_income_entry(
                session,
                reporting_month_id=month.id,
                income_type=IncomeType.SALARY,
                name="Synthetic Salary",
                gross_amount="150000.00",
                tax_amount="0.00",
                net_amount="130000.00",
            )
            result = calculate_salary_tax(session, month.id)
            assert result.tax_kopecks == 2_000_000
            assert [part.rate_bps for part in result.parts] == [1000, 2000]
    finally:
        database.engine.dispose()


def test_tax_bracket_api_rejects_invalid_set_atomically(tmp_path: Path) -> None:
    database = create_database(tmp_path / "tax-brackets-invalid.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            assert client.put("/api/tax-brackets/2036", json=_two_bracket_payload()).status_code == 200

            invalid = client.put(
                "/api/tax-brackets/2036",
                json={
                    "brackets": [
                        _rule("0.00", "100000.00", 1000),
                        _rule("110000.00", None, 2000),
                    ]
                },
            )
            assert invalid.status_code == 422

            after = client.get("/api/tax-brackets/2036")
            assert after.status_code == 200
            assert after.json()["brackets"] == _two_bracket_payload()["brackets"]
    finally:
        database.engine.dispose()


def test_closed_month_locks_tax_year_until_reopened(tmp_path: Path) -> None:
    database = create_database(tmp_path / "tax-brackets-lock.db")
    Base.metadata.create_all(database.engine)
    try:
        with database.session_factory() as session:
            month = create_reporting_month(
                session, year=2037, month=1, snapshot_date=date(2037, 1, 31)
            )
            month.status = ReportingMonthStatus.CLOSED.value
            session.commit()
            month_id = month.id

        with TestClient(create_app(database)) as client:
            locked_read = client.get("/api/tax-brackets/2037")
            assert locked_read.status_code == 200
            assert locked_read.json()["mutable"] is False
            assert locked_read.json()["closed_months"] == ["2037-01"]

            locked = client.put("/api/tax-brackets/2037", json=_two_bracket_payload())
            assert locked.status_code == 409
            error = locked.json()["error"]
            assert error["code"] == "tax_brackets_year_locked"
            assert error["details"] == [{"field": "closed_month", "message": "2037-01"}]
            assert client.get("/api/tax-brackets/2037").json()["source"] == "official_default"

        with database.session_factory() as session:
            month = session.get(ReportingMonth, month_id)
            assert month is not None
            month.status = ReportingMonthStatus.DRAFT.value
            session.commit()

        with TestClient(create_app(database)) as client:
            unlocked = client.put("/api/tax-brackets/2037", json=_two_bracket_payload())
            assert unlocked.status_code == 200
            assert unlocked.json()["mutable"] is True
            assert unlocked.json()["source"] == "manual_configuration"
    finally:
        database.engine.dispose()
