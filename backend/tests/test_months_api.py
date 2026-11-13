"""Integration tests for the reporting months API (D01 + D02 + D08).

Covers the CRUD lifecycle, validation, close/reopen semantics, closed-month
guards, the unified error response contract and list ordering through the
HTTP boundary. Each test builds a fresh in-memory-backed SQLite database via
``create_database`` + ``create_app`` so tests are isolated from each other and
from the production database.
"""

from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, update

from hermes_finance.api import month_close_workflow as workflow_api
from hermes_finance.database import Database, create_database
from hermes_finance.domain.instruments import InstrumentType
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, IncomeEntry
from hermes_finance.services.accounts import create_account
from hermes_finance.services.close_readiness import (
    CloseReadinessItem,
    CloseReadinessSeverity,
)
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.month_checklist import attention_step


@pytest.fixture
def database(tmp_path: Path) -> Generator[Database, None, None]:
    database = create_database(tmp_path / "months_api.db")
    Base.metadata.create_all(database.engine)
    try:
        yield database
    finally:
        database.engine.dispose()


@pytest.fixture
def client(database: Database) -> Generator[TestClient, None, None]:
    with TestClient(create_app(database)) as test_client:
        yield test_client


def _assert_month_body(
    body: dict,
    *,
    year: int,
    month: int,
    snapshot_date: str,
    source: str = "manual",
    status: str = "draft",
) -> None:
    assert set(body) == {"id", "year", "month", "status", "snapshot_date", "source"}
    assert isinstance(body["id"], int)
    assert body["year"] == year
    assert body["month"] == month
    assert body["status"] == status
    assert body["snapshot_date"] == snapshot_date
    assert body["source"] == source


def _assert_error_body(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], list)


def _create(client: TestClient, year: int, month: int, snapshot_date: str) -> dict:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": snapshot_date},
    )
    assert response.status_code == 201
    return response.json()


def test_crud_happy_path(client: TestClient) -> None:
    created = _create(client, 2031, 1, "2031-01-15")
    _assert_month_body(created, year=2031, month=1, snapshot_date="2031-01-15")

    listing = client.get("/api/months")
    assert listing.status_code == 200
    assert listing.json() == [created]

    fetched = client.get(f"/api/months/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    updated = client.patch(f"/api/months/{created['id']}", json={"snapshot_date": "2031-01-20"})
    assert updated.status_code == 200
    assert updated.json()["id"] == created["id"]
    assert updated.json()["snapshot_date"] == "2031-01-20"

    deleted = client.delete(f"/api/months/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    after_delete = client.get(f"/api/months/{created['id']}")
    assert after_delete.status_code == 404
    _assert_error_body(after_delete.json(), "not_found")


def test_create_validation_and_duplicate(client: TestClient) -> None:
    invalid_month = client.post(
        "/api/months", json={"year": 2031, "month": 13, "snapshot_date": "2031-01-15"}
    )
    assert invalid_month.status_code == 422
    invalid_month_body = invalid_month.json()
    _assert_error_body(invalid_month_body, "unprocessable")
    assert any(detail["field"] == "month" for detail in invalid_month_body["error"]["details"])

    extra_field = client.post(
        "/api/months",
        json={"year": 2031, "month": 1, "snapshot_date": "2031-01-15", "bogus": True},
    )
    assert extra_field.status_code == 422
    extra_field_body = extra_field.json()
    _assert_error_body(extra_field_body, "unprocessable")
    assert any(detail["field"] == "bogus" for detail in extra_field_body["error"]["details"])

    missing_snapshot = client.post("/api/months", json={"year": 2031, "month": 1})
    assert missing_snapshot.status_code == 422
    missing_snapshot_body = missing_snapshot.json()
    _assert_error_body(missing_snapshot_body, "unprocessable")
    assert any(
        detail["field"] == "snapshot_date" for detail in missing_snapshot_body["error"]["details"]
    )

    _create(client, 2031, 1, "2031-01-15")
    duplicate = client.post(
        "/api/months", json={"year": 2031, "month": 1, "snapshot_date": "2031-01-15"}
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")


def test_close_and_reopen_cycle(client: TestClient) -> None:
    created = _create(client, 2031, 3, "2031-03-15")
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": created["id"],
                "name": "Recorded cash",
                "amount": {"amount": "0.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )

    closed = client.post(f"/api/months/{created['id']}/close")
    assert closed.status_code == 200
    _assert_month_body(
        closed.json(), year=2031, month=3, snapshot_date="2031-03-15", status="closed"
    )

    closed_again = client.post(f"/api/months/{created['id']}/close")
    assert closed_again.status_code == 200
    assert closed_again.json()["status"] == "closed"

    fetched_closed = client.get(f"/api/months/{created['id']}")
    assert fetched_closed.status_code == 200
    assert fetched_closed.json()["status"] == "closed"

    reopened = client.post(f"/api/months/{created['id']}/reopen")
    assert reopened.status_code == 200
    _assert_month_body(
        reopened.json(), year=2031, month=3, snapshot_date="2031-03-15", status="draft"
    )


def test_closed_month_guards_patch_and_delete(client: TestClient) -> None:
    created = _create(client, 2031, 4, "2031-04-15")
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": created["id"],
                "name": "Recorded cash",
                "amount": {"amount": "0.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )
    closed = client.post(f"/api/months/{created['id']}/close")
    assert closed.status_code == 200

    patched = client.patch(f"/api/months/{created['id']}", json={"snapshot_date": "2031-04-20"})
    assert patched.status_code == 409
    _assert_error_body(patched.json(), "conflict")

    deleted = client.delete(f"/api/months/{created['id']}")
    assert deleted.status_code == 409
    _assert_error_body(deleted.json(), "conflict")


def test_error_contract_codes(client: TestClient) -> None:
    not_found = client.get("/api/months/999999")
    assert not_found.status_code == 404
    _assert_error_body(not_found.json(), "not_found")

    created = _create(client, 2031, 5, "2031-05-15")
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": created["id"],
                "name": "Recorded cash",
                "amount": {"amount": "0.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )
    client.post(f"/api/months/{created['id']}/close")
    conflict = client.patch(f"/api/months/{created['id']}", json={"snapshot_date": "2031-05-20"})
    assert conflict.status_code == 409
    _assert_error_body(conflict.json(), "conflict")

    unprocessable = client.post(
        "/api/months", json={"year": 2031, "month": 13, "snapshot_date": "2031-01-15"}
    )
    assert unprocessable.status_code == 422
    _assert_error_body(unprocessable.json(), "unprocessable")

    method_not_allowed = client.put(f"/api/months/{created['id']}", json={})
    assert method_not_allowed.status_code == 405
    _assert_error_body(method_not_allowed.json(), "method_not_allowed")


def test_health_with_error_handlers_registered(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str)


def test_listing_orders_by_year_then_month(client: TestClient) -> None:
    _create(client, 2031, 2, "2031-02-15")
    _create(client, 2031, 1, "2031-01-15")

    listing = client.get("/api/months")
    assert listing.status_code == 200
    months = listing.json()
    assert [(month["year"], month["month"]) for month in months] == [(2031, 1), (2031, 2)]


def _working_status(client: TestClient) -> dict:
    response = client.get("/api/months/working-status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"month", "completed_steps", "total_steps"}
    assert body["total_steps"] == 10
    return body


def _close(client: TestClient, month_id: int) -> None:
    assert client.post(f"/api/months/{month_id}/close").status_code == 200


def _add_income(client: TestClient, month_id: int) -> None:
    zero = {"amount": "0.00", "currency": "RUB"}
    response = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "other",
            "name": "Synthetic income",
            "gross_amount": zero,
            "tax_amount": zero,
            "net_amount": zero,
        },
    )
    assert response.status_code == 201


def test_working_status_without_months(client: TestClient) -> None:
    assert _working_status(client) == {"month": None, "completed_steps": 0, "total_steps": 10}


def test_working_status_follows_the_close_page_month(client: TestClient) -> None:
    older_draft = _create(client, 2031, 1, "2031-01-31")
    assert _working_status(client)["month"]["id"] == older_draft["id"]

    closed = _create(client, 2031, 2, "2031-02-28")
    _close(client, closed["id"])
    body = _working_status(client)
    assert body["month"]["id"] == closed["id"]
    assert body["month"]["status"] == "closed"

    newer_draft = _create(client, 2031, 3, "2031-03-31")
    body = _working_status(client)
    assert body["month"]["id"] == newer_draft["id"]
    assert body["month"]["status"] == "draft"
    _assert_month_body(body["month"], year=2031, month=3, snapshot_date="2031-03-31")


def test_working_status_counts_saved_sections(client: TestClient, database: Database) -> None:
    month_id = _create(client, 2031, 1, "2031-01-31")["id"]
    assert _working_status(client)["completed_steps"] == 1

    comment = {"reporting_month_id": month_id, "text": "Synthetic note"}
    assert client.post("/api/comments", json=comment).status_code == 201
    assert _working_status(client)["completed_steps"] == 2

    _add_income(client, month_id)
    assert _working_status(client)["completed_steps"] == 3

    # A row without saved-actual provenance, as after a clone, proves nothing.
    with database.session_factory() as session:
        session.execute(update(IncomeEntry).values(actual_fact_origin=None))
        session.commit()
    assert _working_status(client)["completed_steps"] == 2

    _close(client, month_id)
    assert _working_status(client)["completed_steps"] == 3


def test_working_status_stays_one_month_query_and_one_facts_query(
    client: TestClient, database: Database
) -> None:
    month_id = _create(client, 2031, 1, "2031-01-31")["id"]
    _add_income(client, month_id)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        assert _working_status(client)["completed_steps"] == 2
    finally:
        event.remove(database.engine, "before_cursor_execute", record)

    selects = [item for item in statements if item.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2
    assert "FROM reporting_months" in selects[0]
    assert "EXISTS" in selects[1]


# Month page checklist inside the close workflow read (#1079, stage 2). It is
# presentation: it must agree with the sidebar plate and not change readiness.

STEP_IDS = [
    "general",
    "income",
    "assets",
    "liabilities",
    "budget",
    "brokers",
    "positions",
    "payouts",
    "note",
    "close",
]


def _money(amount: str) -> dict:
    return {"amount": amount, "currency": "RUB"}


def _checklist_month(client: TestClient, snapshot_date: str = "2031-01-31") -> int:
    response = client.post(
        "/api/months", json={"year": 2031, "month": 1, "snapshot_date": snapshot_date}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _checklist_workflow(client: TestClient, month_id: int) -> dict:
    response = client.get(f"/api/months/{month_id}/close-workflow?include_checklist=true")
    assert response.status_code == 200, response.text
    return response.json()


def _checklist_steps(body: dict) -> dict[str, dict]:
    return {step["id"]: step for step in body["checklist"]["steps"]}


def _checklist_expense(
    client: TestClient, month_id: int, category: str, amount: str, kind: str
) -> None:
    response = client.post(
        "/api/expenses",
        json={
            "reporting_month_id": month_id,
            "category": category,
            "amount": _money(amount),
            "expense_type": kind,
        },
    )
    assert response.status_code == 201, response.text


def test_empty_month_lists_ten_steps_without_figures(client: TestClient) -> None:
    month_id = _checklist_month(client)
    checklist = _checklist_workflow(client, month_id)["checklist"]

    assert [step["id"] for step in checklist["steps"]] == STEP_IDS
    assert [step["group"] for step in checklist["steps"]] == [
        *["data"] * 5,
        *["sources"] * 3,
        "plan",
        "close",
    ]
    assert checklist["total_count"] == 10
    assert checklist["completed_count"] == 1
    steps = _checklist_steps({"checklist": checklist})
    assert steps["general"]["state"] == "done"
    assert steps["general"]["figure"] == {
        "kind": "date",
        "amount": None,
        "day": "2031-01-31",
        "count": None,
    }
    assert steps["note"]["state"] == "optional"
    assert steps["note"]["required"] is False
    for step_id in ("income", "assets", "positions", "budget", "close"):
        assert steps[step_id]["state"] == "empty"
        # An empty section shows no figure rather than a zero fact.
        assert steps[step_id]["figure"] is None
        assert steps[step_id]["secondary_count"] is None


def test_checklist_count_matches_the_sidebar_plate(client: TestClient) -> None:
    month_id = _checklist_month(client)
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": month_id,
                "name": "Synthetic cash",
                "amount": _money("10.00"),
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/comments", json={"reporting_month_id": month_id, "text": "Synthetic note"}
        ).status_code
        == 201
    )

    plate = client.get("/api/months/working-status").json()
    checklist = _checklist_workflow(client, month_id)["checklist"]
    assert checklist["completed_count"] == plate["completed_steps"] == 3
    assert checklist["total_count"] == plate["total_steps"]

    steps = _checklist_steps({"checklist": checklist})
    assert steps["assets"]["state"] == "done"
    assert steps["assets"]["figure"]["amount"] == _money("10.00")
    assert steps["note"]["state"] == "done"
    assert steps["note"]["figure"] == {"kind": "count", "amount": None, "day": None, "count": 1}


def test_expenses_keep_mandatory_and_other_totals_apart(client: TestClient) -> None:
    month_id = _checklist_month(client)
    _checklist_expense(client, month_id, "Synthetic rent", "300.00", "mandatory")
    _checklist_expense(client, month_id, "Synthetic phone", "20.00", "mandatory")
    _checklist_expense(client, month_id, "Synthetic phone", "5.00", "mandatory")
    _checklist_expense(client, month_id, "Synthetic cinema", "7.50", "other")

    body = _checklist_workflow(client, month_id)
    expenses = body["checklist"]["expenses"]
    assert expenses["mandatory_items"] == [
        {"category": "Synthetic rent", "amount": _money("300.00")},
        {"category": "Synthetic phone", "amount": _money("25.00")},
    ]
    assert expenses["mandatory_total"] == _money("325.00")
    # The overview KPI and the item list use one mandatory total.
    assert body["final_review"]["kpis"]["mandatory_expenses"] == _money("325.00")
    assert expenses["other_total"] == _money("7.50")

    budget = _checklist_steps(body)["budget"]
    assert budget["state"] == "done"
    assert budget["figure"]["amount"] == _money("325.00")
    assert budget["secondary_count"] == 3


def test_readiness_warning_marks_its_section(client: TestClient) -> None:
    month_id = _checklist_month(client)
    account = {"name": "Synthetic broker", "account_type": "brokerage"}
    assert client.post("/api/accounts", json=account).status_code == 201

    body = _checklist_workflow(client, month_id)
    codes = [item["code"] for item in body["final_review"]["close_readiness"]["items"]]
    assert "active_account_snapshot_missing" in codes
    positions = _checklist_steps(body)["positions"]
    assert positions["state"] == "attention"
    assert positions["attention_count"] == 1
    assert positions["has_saved_facts"] is False
    assert body["checklist"]["attention_count"] >= 1
    # Presentation never changes the close decision.
    assert body["readiness"]["can_close"] is True


def test_closed_month_completes_the_close_step(client: TestClient) -> None:
    month_id = _checklist_month(client)
    assert (
        client.post(
            "/api/comments", json={"reporting_month_id": month_id, "text": "Synthetic note"}
        ).status_code
        == 201
    )
    readiness_before = _checklist_workflow(client, month_id)["readiness"]
    assert client.post(f"/api/months/{month_id}/close").status_code == 200

    body = _checklist_workflow(client, month_id)
    assert _checklist_steps(body)["close"]["state"] == "done"
    assert body["checklist"]["completed_count"] == 3
    assert readiness_before["can_close"] is True


def _readiness_item(code: str, severity: str = "warning", **context: object) -> CloseReadinessItem:
    return CloseReadinessItem(
        severity=CloseReadinessSeverity(severity), code=code, message="", context=context
    )


def test_attention_step_routes_findings_to_sections() -> None:
    assert attention_step(_readiness_item("snapshot_date_required")) == "general"
    assert attention_step(_readiness_item("salary_tax_history_incomplete")) == "income"
    assert attention_step(_readiness_item("active_account_snapshot_missing")) == "positions"
    assert attention_step(_readiness_item("unresolved_payout_reconciliation")) == "payouts"
    assert attention_step(_readiness_item("quote_stale", family_id="market_quotes")) == "positions"
    assert attention_step(_readiness_item("x", family_id="deposit_cash_snapshots")) == "assets"
    assert attention_step(_readiness_item("x", family_id="alfa_statement_payouts")) == "brokers"
    assert attention_step(_readiness_item("cash_control_mismatch", "hard_blocker")) == "brokers"
    # Information and a month-wide empty finding are not section findings.
    assert attention_step(_readiness_item("backup_none", "info")) is None
    assert attention_step(_readiness_item("empty_manual_month")) is None


def test_checklist_is_built_only_for_the_month_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    month_id = _checklist_month(client)
    calls: list[int] = []
    original = workflow_api.build_month_checklist

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow_api, "build_month_checklist", counted)
    # Other callers, such as the Home draft action, keep the lighter read.
    plain = client.get(f"/api/months/{month_id}/close-workflow")
    assert plain.status_code == 200, plain.text
    assert plain.json()["checklist"] is None
    assert calls == []

    assert _checklist_workflow(client, month_id)["checklist"]["total_count"] == 10
    assert calls == [1]


def _flow(session, month_id: int, account_id: int, flow_type: str, instrument_id=None) -> None:
    create_investment_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        event_date=date(2031, 1, 20),
        gross_amount="10.00",
        net_amount="10.00",
        source="synthetic",
    )


def test_payout_counts_follow_payouts_and_the_calendar(
    client: TestClient, database: Database
) -> None:
    month_id = _checklist_month(client)
    with database.session_factory() as session:
        account = create_account(session, name="Synthetic broker", account_type="brokerage")
        bond = create_instrument(
            session, name="Synthetic bond", instrument_type=InstrumentType.BOND
        )
        _flow(session, month_id, account.id, "commission")
        account_id, bond_id = account.id, bond.id

    # A fee fills the section but is not a received payout.
    payouts = _checklist_steps(_checklist_workflow(client, month_id))["payouts"]
    assert payouts["has_saved_facts"] is True
    assert payouts["figure"]["count"] == 0
    assert payouts["secondary_count"] == 0

    with database.session_factory() as session:
        _flow(session, month_id, account_id, "coupon", bond_id)
        create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=bond_id,
            flow_type="coupon",
            expected_date=date(2031, 3, 14),
            gross_amount="12.00",
            expected_net_amount="12.00",
            source="synthetic calendar",
            source_as_of_date=date(2031, 1, 31),
            forecast_version="v1",
        )
        # Outside the calendar year after the snapshot: not on the calendar.
        create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=bond_id,
            flow_type="coupon",
            expected_date=date(2033, 3, 14),
            gross_amount="12.00",
            expected_net_amount="12.00",
            source="synthetic calendar",
            source_as_of_date=date(2031, 1, 31),
            forecast_version="v1",
        )

    payouts = _checklist_steps(_checklist_workflow(client, month_id))["payouts"]
    assert payouts["figure"]["count"] == 1
    assert payouts["secondary_count"] == 1


def test_cloned_templates_require_explicit_unchanged_amount_confirmation(
    client: TestClient,
) -> None:
    source = client.post(
        "/api/months", json={"year": 2040, "month": 1, "snapshot_date": "2040-01-31"}
    ).json()
    money = {"amount": "123.45", "currency": "RUB"}
    created = client.post(
        "/api/expenses",
        json={
            "reporting_month_id": source["id"],
            "category": "Synthetic",
            "amount": money,
            "expense_type": "mandatory",
            "is_recurring": True,
        },
    )
    assert created.status_code == 201
    clone = client.post(
        f"/api/months/{source['id']}/clone",
        json={"year": 2040, "month": 2, "snapshot_date": "2040-02-29"},
    )
    assert clone.status_code == 201
    mid = clone.json()["id"]

    def budget() -> dict:
        response = client.get(f"/api/months/{mid}/close-workflow?include_checklist=true")
        assert response.status_code == 200
        return next(
            step for step in response.json()["checklist"]["steps"] if step["id"] == "budget"
        )

    assert budget()["has_templates"] is True
    assert budget()["has_saved_facts"] is False
    row = client.get(f"/api/expenses?month_id={mid}").json()[0]
    assert row["actual_fact_origin"] == "clone_template_v1"
    assert (
        client.patch(f"/api/expenses/{row['id']}", json={"notes": "Synthetic note"}).status_code
        == 200
    )
    assert budget()["has_saved_facts"] is False
    confirmed = client.patch(f"/api/expenses/{row['id']}", json={"amount": row["amount"]})
    assert confirmed.status_code == 200
    assert confirmed.json()["amount"] == money
    assert confirmed.json()["actual_fact_origin"] == "saved_actual_v1"
    assert budget()["has_templates"] is False
    assert budget()["has_saved_facts"] is True
