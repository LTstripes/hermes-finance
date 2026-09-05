"""API tests for the bounded current-state Tax/IIS Planner (R07-10a)."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.tax_brackets import list_tax_brackets


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "tax_iis_planner.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _create_month(client: TestClient, month: int, *, year: int = 2031) -> int:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": f"{year}-{month:02d}-28"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_salary(client: TestClient, month_id: int, gross: str, net: str = "0.00") -> None:
    response = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "salary",
            "name": "Synthetic Salary",
            "gross_amount": _rub(gross),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub(net),
        },
    )
    assert response.status_code == 201, response.text


def _create_iis(client: TestClient) -> dict:
    account_response = client.post(
        "/api/accounts", json={"name": "Synthetic IIS", "account_type": "iis"}
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()
    profile_response = client.put(
        f"/api/iis/{account['id']}/profile",
        json={
            "iis_type": "type_a",
            "opened_at": "2031-01-01",
            "eligible_close_at": "2036-01-01",
        },
    )
    assert profile_response.status_code == 200, profile_response.text
    return account


def test_planner_uses_authoritative_salary_context_and_separates_benefit_statuses(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "2000000.00")
    assert client.post(f"/api/months/{january_id}/close").status_code == 200

    february_id = _create_month(client, 2)
    _add_salary(client, february_id, "500000.00")
    account = _create_iis(client)

    contribution = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00"), "is_target_reached": True},
    )
    assert contribution.status_code == 201, contribution.text
    for status, amount, benefit_type in (
        ("planned", "60000.00", "planned_a"),
        ("submitted", "50000.00", "submitted_a"),
        ("received", "40000.00", "received_a"),
        ("rejected", "10000.00", "rejected_a"),
    ):
        response = client.post(
            f"/api/iis/{account['id']}/benefits",
            json={
                "tax_year": 2031,
                "benefit_type": benefit_type,
                "status": status,
                "amount": _rub(amount),
            },
        )
        assert response.status_code == 201, response.text

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={february_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract_version"] == "tax_iis_planner_v1"
    assert body["tax_year"] == 2031
    assert body["as_of"]["reporting_month"]["id"] == february_id
    assert body["as_of"]["selection_reason"] == "requested"

    salary = body["salary_tax"]
    assert salary["history_complete"] is True
    assert salary["available"] is True
    assert salary["taxable_gross_ytd"] == _rub("2500000.00")
    assert salary["current_marginal_rate_bps"] == 1500
    assert salary["current_marginal_bracket"] == {
        "threshold_from": _rub("2400000.00"),
        "threshold_to": _rub("5000000.00"),
        "rate_bps": 1500,
    }
    assert salary["next_threshold"] == _rub("5000000.00")
    assert salary["distance_to_next_threshold"] == _rub("2500000.00")
    assert salary["warning_codes"] == []

    planner_iis = body["iis_accounts"]
    assert len(planner_iis) == 1
    assert planner_iis[0]["account_id"] == account["id"]
    assert planner_iis[0]["contributions_by_tax_year"] == [
        {"tax_year": 2031, "amount": _rub("400000.00"), "is_target_reached": True}
    ]
    assert planner_iis[0]["tax_benefits"] == {
        "planned": _rub("60000.00"),
        "submitted": _rub("50000.00"),
        "received": _rub("40000.00"),
        "rejected": _rub("10000.00"),
    }
    # The planner is intentionally not an IIS securities-result endpoint.
    assert "portfolio_result_without_tax_benefit" not in planner_iis[0]
    assert "cost_basis" not in planner_iis[0]


def test_planner_fails_closed_for_incomplete_salary_history_but_keeps_iis_context(
    client: TestClient,
) -> None:
    march_id = _create_month(client, 3)
    _add_salary(client, march_id, "300000.00")
    account = _create_iis(client)
    benefit = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "type_a",
            "status": "received",
            "amount": _rub("39000.00"),
        },
    )
    assert benefit.status_code == 201, benefit.text

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={march_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    salary = body["salary_tax"]
    assert salary["history_complete"] is False
    assert salary["history_coverage"] == "unavailable"
    assert salary["available"] is False
    assert salary["taxable_gross_ytd"] is None
    assert salary["current_marginal_bracket"] is None
    assert salary["current_marginal_rate_bps"] is None
    assert salary["next_threshold"] is None
    assert salary["distance_to_next_threshold"] is None
    assert salary["warning_codes"] == ["salary_tax_history_incomplete"]
    assert body["warnings"] == ["salary_tax_history_incomplete"]
    assert body["iis_accounts"][0]["tax_benefits"]["received"] == _rub("39000.00")


def test_default_planner_selection_prefers_latest_closed_month(client: TestClient) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "100000.00")
    assert client.post(f"/api/months/{january_id}/close").status_code == 200

    february_id = _create_month(client, 2)
    _add_salary(client, february_id, "200000.00")

    response = client.get("/api/tax-iis-planner")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["as_of"]["reporting_month"]["id"] == january_id
    assert body["as_of"]["selection_reason"] == "latest_closed"
    assert body["salary_tax"]["taxable_gross_ytd"] == _rub("100000.00")


def test_planner_read_does_not_seed_tax_brackets(client: TestClient) -> None:
    month_id = _create_month(client, 1)
    _add_salary(client, month_id, "100000.00")

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={month_id}")

    assert response.status_code == 200, response.text
    with client:
        database = client.app.state.database
        with database.session_factory() as session:
            assert list_tax_brackets(session, 2031) == []


def test_planner_january_ytd_is_payment_only_with_first_bracket(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "300000.00")

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={january_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["history_complete"] is True
    assert salary["available"] is True
    assert salary["taxable_gross_ytd"] == _rub("300000.00")
    assert salary["current_marginal_rate_bps"] == 1300
    assert salary["current_marginal_bracket"] == {
        "threshold_from": _rub("0.00"),
        "threshold_to": _rub("2400000.00"),
        "rate_bps": 1300,
    }
    assert salary["next_threshold"] == _rub("2400000.00")
    assert salary["distance_to_next_threshold"] == _rub("2100000.00")
    assert salary["warning_codes"] == []


def test_planner_zero_payment_with_incomplete_history_stays_fail_closed(
    client: TestClient,
) -> None:
    # No salary entries at all: the payment itself is zero, but prior YTD is
    # unknown, so the bracket/distance must stay unavailable, never guessed.
    march_id = _create_month(client, 3)

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={march_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["history_complete"] is False
    assert salary["available"] is False
    assert salary["taxable_gross_ytd"] is None
    assert salary["current_marginal_bracket"] is None
    assert salary["current_marginal_rate_bps"] is None
    assert salary["distance_to_next_threshold"] is None
    assert salary["warning_codes"] == ["salary_tax_history_incomplete"]


def test_planner_zero_payment_with_complete_history_keeps_prior_ytd(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "2000000.00")
    assert client.post(f"/api/months/{january_id}/close").status_code == 200

    february_id = _create_month(client, 2)

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={february_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["history_complete"] is True
    assert salary["available"] is True
    assert salary["taxable_gross_ytd"] == _rub("2000000.00")
    assert salary["current_marginal_rate_bps"] == 1300
    assert salary["distance_to_next_threshold"] == _rub("400000.00")
    assert salary["warning_codes"] == []


def test_planner_applies_opening_context_once(client: TestClient) -> None:
    opening = client.put(
        "/api/salary-tax/years/2031/opening-context",
        json={
            "effective_from_month": 5,
            "opening_taxable_gross": _rub("400000.00"),
        },
    )
    assert opening.status_code == 200, opening.text

    may_id = _create_month(client, 5)
    _add_salary(client, may_id, "100000.00")
    assert client.post(f"/api/months/{may_id}/close").status_code == 200

    june_id = _create_month(client, 6)
    _add_salary(client, june_id, "100000.00")

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={june_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["history_complete"] is True
    assert salary["available"] is True
    assert salary["opening_context_available"] is True
    assert salary["taxable_gross_ytd"] == _rub("600000.00")
    assert salary["current_marginal_rate_bps"] == 1300
    assert salary["distance_to_next_threshold"] == _rub("1800000.00")
    assert salary["warning_codes"] == []


def test_planner_exact_threshold_crossing_uses_next_bracket(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "2400000.00")

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={january_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["available"] is True
    assert salary["taxable_gross_ytd"] == _rub("2400000.00")
    assert salary["current_marginal_rate_bps"] == 1500
    assert salary["current_marginal_bracket"] == {
        "threshold_from": _rub("2400000.00"),
        "threshold_to": _rub("5000000.00"),
        "rate_bps": 1500,
    }
    assert salary["next_threshold"] == _rub("5000000.00")
    assert salary["distance_to_next_threshold"] == _rub("2600000.00")


def test_planner_above_threshold_reports_exact_remaining_distance(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "6000000.00")

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={january_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["available"] is True
    assert salary["taxable_gross_ytd"] == _rub("6000000.00")
    assert salary["current_marginal_rate_bps"] == 1800
    assert salary["next_threshold"] == _rub("20000000.00")
    assert salary["distance_to_next_threshold"] == _rub("14000000.00")


def test_planner_open_ended_top_bracket_has_no_next_threshold(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "55000000.00")

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={january_id}")

    assert response.status_code == 200, response.text
    salary = response.json()["salary_tax"]
    assert salary["available"] is True
    assert salary["taxable_gross_ytd"] == _rub("55000000.00")
    assert salary["current_marginal_rate_bps"] == 2200
    assert salary["current_marginal_bracket"]["threshold_to"] is None
    assert salary["next_threshold"] is None
    assert salary["distance_to_next_threshold"] is None


def test_planner_without_iis_data_returns_empty_iis_section(
    client: TestClient,
) -> None:
    january_id = _create_month(client, 1)
    _add_salary(client, january_id, "100000.00")
    assert client.post(f"/api/months/{january_id}/close").status_code == 200

    response = client.get(f"/api/tax-iis-planner?reporting_month_id={january_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["iis_accounts"] == []
    assert body["salary_tax"]["available"] is True


def test_planner_unknown_reporting_month_is_not_found(
    client: TestClient,
) -> None:
    response = client.get("/api/tax-iis-planner?reporting_month_id=999999")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
