"""R07-04 monthly close readiness: advisory checklist, no invented blockers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExpectedCashFlowType,
    IncomeType,
    InstrumentType,
    PriceSource,
)
from hermes_finance.domain.month_close_workflow import (
    GuidedCloseApplicability,
    GuidedCloseGate,
    GuidedCloseStep,
    GuidedCloseStepId,
    GuidedCloseStepState,
    derive_step_state,
    recommended_step_id,
)
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.persistence import (
    Base,
    BrokerBaselineApply,
    BrokerBaselineApplyItem,
    ExpectedCashFlow,
    InstrumentMarketMapping,
    PositionQuoteProvenance,
    PositionSnapshot,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    PayoutCountingDecision,
    create_applied_payout,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.applied_statement_events import (
    StatementLinkMode,
    create_applied_statement_event,
)
from hermes_finance.services.backups import create_backup
from hermes_finance.services.close_readiness import (
    CloseReadinessCode,
    CloseReadinessSeverity,
    build_close_readiness,
)
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.freshness_provenance import FreshnessReasonCode
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.positions import (
    apply_snapshot_market_quote,
    create_position_snapshot,
    stage_update_position_snapshot,
)
from hermes_finance.services.reporting_months import (
    CLOSE_SNAPSHOT_DATE_REQUIRED_CODE,
    CLOSE_SNAPSHOT_DATE_REQUIRED_MESSAGE,
    close_hard_guards,
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)
from hermes_finance.services.statement_import_retract import retract_applied_statement_event
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER

TODAY = date(2026, 8, 27)
FETCHED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
APPLIED_AT = datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
BOND_UID = "33333333-3333-3333-3333-333333333333"
EXPECTED_WORKFLOW_STEP_IDS = [
    "month_setup",
    "alfa_baseline",
    "market_quotes",
    "actual_payouts",
    "future_payouts",
    "broker_reconciliation",
    "readiness",
    "final_review_close",
    "next_month_outlook",
]


def session_for(tmp_path: Path):
    database = create_database(tmp_path / "close-readiness.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _codes(result) -> list[str]:
    return [item.code for item in result.items]


def _by_code(result, code: str):
    return [item for item in result.items if item.code == code]


def _severities(result) -> list[str]:
    return [item.severity.value for item in result.items]


def _t_invest_snapshot(
    session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    price_date: date,
    kopecks: int = 10000,
):
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity="1",
        average_cost_per_unit="100.00",
        market_price_per_unit="100.00",
        price_date=price_date,
        price_source=PriceSource.MANUAL,
    )
    apply_snapshot_market_quote(
        session,
        snapshot,
        market_price_per_unit_kopecks=kopecks,
        price_date=price_date,
        price_source=PriceSource.T_INVEST,
    )
    session.commit()
    session.refresh(snapshot)
    return snapshot


def _add_quote_provenance(
    session,
    snapshot: PositionSnapshot,
    *,
    price_date: date,
    freshness: str = "ok",
) -> None:
    session.add(
        PositionQuoteProvenance(
            position_snapshot_id=snapshot.id,
            reporting_month_id=snapshot.reporting_month_id,
            provider="t_invest",
            provider_instrument_id=STOCK_UID,
            provider_venue_id=None,
            quote_kind="last",
            raw_price="215.50",
            raw_price_basis="R",
            normalized_price_kopecks=21550,
            price_date=price_date,
            fetched_at_utc=FETCHED_AT,
            target_date=price_date,
            freshness=freshness,
            applied_at_utc=APPLIED_AT,
        )
    )
    session.commit()


def test_close_hard_guards_only_missing_snapshot_date() -> None:
    assert close_hard_guards(SimpleNamespace(snapshot_date=date(2026, 1, 31))) == ()
    assert close_hard_guards(SimpleNamespace(snapshot_date=None)) == (
        (CLOSE_SNAPSHOT_DATE_REQUIRED_CODE, CLOSE_SNAPSHOT_DATE_REQUIRED_MESSAGE),
    )


def test_empty_january_draft_has_no_invented_hard_blockers(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    result = build_close_readiness(session, month.id, today=TODAY)
    assert result.can_close is True
    assert result.status == "draft"
    assert CloseReadinessSeverity.HARD_BLOCKER.value not in _severities(result)
    assert CloseReadinessCode.SNAPSHOT_DATE_REQUIRED.value not in _codes(result)
    assert CloseReadinessCode.SALARY_TAX_HISTORY_INCOMPLETE.value not in _codes(result)
    assert "positions_required" not in _codes(result)
    assert "expenses_required" not in _codes(result)
    assert "salary_required" not in _codes(result)
    empty_or_absent = {
        CloseReadinessCode.SECTION_EMPTY.value,
        FreshnessReasonCode.PAYOUT_NONE_FOR_MONTH.value,
        FreshnessReasonCode.STATEMENT_NONE_FOR_MONTH.value,
        FreshnessReasonCode.MANUAL_MONTH_DATA_EMPTY.value,
        FreshnessReasonCode.DEPOSIT_CASH_EMPTY.value,
        FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_PERSISTED.value,
        CloseReadinessCode.PROVENANCE_SUMMARY.value,
        CloseReadinessCode.BACKUP_NONE.value,
    }
    for item in result.items:
        if item.severity is CloseReadinessSeverity.WARNING:
            raise AssertionError(f"empty January must not warn: {item.code}")
        assert item.code in empty_or_absent
        assert item.severity is CloseReadinessSeverity.INFO


def test_populated_january_can_close_without_stale_or_tax_warning(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    stock = create_instrument(session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK)
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type=IncomeType.SALARY,
        name="Зарплата",
        gross_amount="100000.00",
        tax_amount="13000.00",
        net_amount="87000.00",
    )
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 1, 30),
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 1, 30))
    result = build_close_readiness(session, month.id, today=date(2026, 1, 31))
    assert result.can_close is True
    assert CloseReadinessCode.SALARY_TAX_HISTORY_INCOMPLETE.value not in _codes(result)
    assert FreshnessReasonCode.QUOTE_STALE.value not in _codes(result)
    assert CloseReadinessSeverity.HARD_BLOCKER.value not in _severities(result)


def test_incomplete_salary_tax_history_is_warning_not_blocker(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type=IncomeType.SALARY,
        name="Зарплата",
        gross_amount="100000.00",
        tax_amount="13000.00",
        net_amount="87000.00",
    )
    result = build_close_readiness(session, month.id, today=date(2031, 5, 31))
    tax_items = _by_code(result, CloseReadinessCode.SALARY_TAX_HISTORY_INCOMPLETE.value)
    assert len(tax_items) == 1
    assert tax_items[0].severity is CloseReadinessSeverity.WARNING
    assert result.can_close is True
    assert CloseReadinessSeverity.HARD_BLOCKER.value not in _severities(result)


def test_active_capital_account_without_monthly_snapshot_is_warning(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=date(2026, 8, 31))
    create_account(session, name="Synthetic Missing Snapshot", account_type=AccountType.BROKERAGE)

    result = build_close_readiness(session, month.id, today=TODAY)

    missing = _by_code(result, CloseReadinessCode.ACTIVE_ACCOUNT_SNAPSHOT_MISSING.value)
    assert len(missing) == 1
    assert missing[0].severity is CloseReadinessSeverity.WARNING
    assert missing[0].context["account_names"] == ["Synthetic Missing Snapshot"]
    assert result.can_close is True


def test_persisted_stale_quote_is_warning_from_freshness_codes(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=date(2026, 8, 31))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    stock = create_instrument(session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 8, 10),
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 8, 10))
    result = build_close_readiness(session, month.id, today=TODAY)
    stale = _by_code(result, FreshnessReasonCode.QUOTE_STALE.value)
    assert len(stale) == 1
    assert stale[0].severity is CloseReadinessSeverity.WARNING
    assert stale[0].context["family_id"] == "market_quotes"
    assert result.can_close is True
    assert CloseReadinessSeverity.HARD_BLOCKER.value not in _severities(result)


def test_unresolved_payout_reconciliation_is_warning_not_blocker(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="3.125000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    create_applied_payout(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        source_position_snapshot_id=snapshot.id,
        provider="t_invest",
        provider_instrument_uid=BOND_UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key="n:11",
        payment_date=date(2030, 6, 15),
        per_unit_amount=Decimal("35.400000000"),
        currency="RUB",
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )
    session.commit()
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2030, 6, 14),
        gross_amount="1100.00",
        expected_tax_amount="130.00",
        expected_net_amount="970.00",
        source="synthetic calendar",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )
    result = build_close_readiness(session, month.id, today=date(2030, 5, 12))
    unresolved = _by_code(result, CloseReadinessCode.UNRESOLVED_PAYOUT_RECONCILIATION.value)
    assert len(unresolved) == 1
    assert unresolved[0].severity is CloseReadinessSeverity.WARNING
    assert unresolved[0].context["count"] == 1
    assert result.can_close is True


def test_explicit_count_manual_is_resolved_and_does_not_warn(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="3.125000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    payout = create_applied_payout(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        source_position_snapshot_id=snapshot.id,
        provider="t_invest",
        provider_instrument_uid=BOND_UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key="n:11",
        payment_date=date(2030, 6, 15),
        per_unit_amount=Decimal("35.400000000"),
        currency="RUB",
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )
    session.commit()
    manual = create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2030, 6, 14),
        gross_amount="1100.00",
        expected_tax_amount="130.00",
        expected_net_amount="970.00",
        source="synthetic calendar",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )
    set_applied_payout_reconciliation(
        session,
        payout.id,
        expected_cash_flow_id=manual.id,
        counting_decision=PayoutCountingDecision.COUNT_MANUAL,
    )
    session.commit()
    result = build_close_readiness(session, month.id, today=date(2030, 5, 12))
    assert CloseReadinessCode.UNRESOLVED_PAYOUT_RECONCILIATION.value not in _codes(result)
    assert result.can_close is True


def test_closed_month_is_lifecycle_info_not_financial_blocker(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    close_reporting_month(session, month.id)
    result = build_close_readiness(session, month.id, today=TODAY)
    closed = _by_code(result, CloseReadinessCode.MONTH_ALREADY_CLOSED.value)
    assert len(closed) == 1
    assert closed[0].severity is CloseReadinessSeverity.INFO
    assert result.status == "closed"
    assert result.can_close is True
    assert CloseReadinessSeverity.HARD_BLOCKER.value not in _severities(result)


def test_items_are_ordered_hard_blocker_then_warning_then_info(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    result = build_close_readiness(session, month.id, today=date(2031, 5, 31))
    order = {"hard_blocker": 0, "warning": 1, "info": 2}
    previous_key = (-1, "", "")
    for item in result.items:
        key = (order[item.severity.value], item.code, item.message)
        assert key >= previous_key
        previous_key = key


def test_readiness_is_read_only(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    before_status = month.status
    before_provenance = session.scalar(select(func.count()).select_from(PositionQuoteProvenance))
    build_close_readiness(session, month.id, today=TODAY)
    session.refresh(month)
    after_provenance = session.scalar(select(func.count()).select_from(PositionQuoteProvenance))
    assert month.status == before_status
    assert after_provenance == before_provenance


def test_api_returns_readiness_and_close_still_succeeds_with_warnings(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    application = create_app(database)
    application.state.quote_preview_clock = lambda: date(2031, 5, 31)
    client = TestClient(application)
    missing = client.get("/api/months/999/close-readiness")
    assert missing.status_code == 404
    response = client.get(f"/api/months/{month.id}/close-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["can_close"] is True
    assert body["year"] == 2031
    assert body["month"] == 5
    assert body["status"] == "draft"
    assert "month_id" not in body
    assert {item["code"] for item in body["items"] if item["severity"] == "hard_blocker"} == set()
    assert any(
        item["code"] == CloseReadinessCode.SALARY_TAX_HISTORY_INCOMPLETE.value
        and item["severity"] == "warning"
        for item in body["items"]
    )
    closed = client.post(f"/api/months/{month.id}/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    after = client.get(f"/api/months/{month.id}/close-readiness")
    assert after.status_code == 200
    payload = after.json()
    assert payload["status"] == "closed"
    assert payload["can_close"] is True
    assert any(
        item["code"] == CloseReadinessCode.MONTH_ALREADY_CLOSED.value for item in payload["items"]
    )


def test_api_exposes_backup_presence_as_info(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    create_backup(database)
    application = create_app(database)
    application.state.quote_preview_clock = lambda: TODAY
    client = TestClient(application)
    body = client.get(f"/api/months/{month.id}/close-readiness").json()
    present = [
        item for item in body["items"] if item["code"] == CloseReadinessCode.BACKUP_PRESENT.value
    ]
    assert len(present) == 1
    assert present[0]["severity"] == "info"
    assert "created_at" in present[0]["context"]


def test_readiness_does_not_perform_network_calls(tmp_path: Path, monkeypatch) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))

    def boom(*_args, **_kwargs):
        raise AssertionError("close readiness must not call the network")

    monkeypatch.setattr("socket.create_connection", boom)
    monkeypatch.setattr("socket.getaddrinfo", boom)
    result = build_close_readiness(session, month.id, today=TODAY)
    assert result.can_close is True


def test_workflow_state_table_observes_normative_precedence() -> None:
    assert (
        derive_step_state(
            hard_blocked=True,
            not_applicable=True,
            stale_or_partial=True,
            completed=True,
            ready=True,
        )
        is GuidedCloseStepState.BLOCKED
    )
    assert (
        derive_step_state(not_applicable=True, stale_or_partial=True, completed=True)
        is GuidedCloseStepState.SKIPPED
    )
    assert (
        derive_step_state(stale_or_partial=True, completed=True, ready=True)
        is GuidedCloseStepState.WARNING
    )
    assert derive_step_state(completed=True, ready=True) is GuidedCloseStepState.COMPLETED
    assert derive_step_state(ready=True) is GuidedCloseStepState.READY
    assert derive_step_state() is GuidedCloseStepState.NOT_STARTED

    blocked = GuidedCloseStep(
        id=GuidedCloseStepId.MONTH_SETUP,
        order=1,
        title="setup",
        state=GuidedCloseStepState.BLOCKED,
        applicability=GuidedCloseApplicability.MANDATORY,
        gate=GuidedCloseGate.MUST_RESOLVE,
        affects_close=True,
        why="blocked",
    )
    warning = GuidedCloseStep(
        id=GuidedCloseStepId.READINESS,
        order=2,
        title="readiness",
        state=GuidedCloseStepState.WARNING,
        applicability=GuidedCloseApplicability.MANDATORY,
        gate=GuidedCloseGate.ADVISORY,
        affects_close=False,
        why="warning",
    )
    assert recommended_step_id((warning, blocked)) == "month_setup"


class _FailIfCalledProvider:
    def __getattr__(self, name: str):
        raise AssertionError(f"workflow GET must not resolve provider method {name}")


def test_workflow_api_is_month_scoped_read_only_and_provider_free(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    older = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    requested = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    before_month_statuses = [older.status, requested.status]
    application = create_app(
        database,
        market_data_provider=_FailIfCalledProvider(),
        payout_provider=_FailIfCalledProvider(),
        broker_snapshot_provider=_FailIfCalledProvider(),
    )
    application.state.quote_preview_clock = lambda: date(2031, 5, 31)
    application.state.freshness_generated_at = lambda: datetime(
        2031, 5, 31, 12, 0, tzinfo=timezone.utc
    )

    client = TestClient(application)
    response = client.get(f"/api/months/{requested.id}/close-workflow")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "monthly_close_workflow_v1"
    assert body["month"] == {
        "id": requested.id,
        "year": 2031,
        "month": 5,
        "status": "draft",
        "snapshot_date": "2031-05-31",
        "source": "manual",
    }
    assert body["recommended_step_id"] == "alfa_baseline"
    assert [step["order"] for step in body["steps"]] == list(range(1, 10))
    draft_step_ids = [step["id"] for step in body["steps"]]
    assert draft_step_ids == EXPECTED_WORKFLOW_STEP_IDS
    assert len(draft_step_ids) == len(set(draft_step_ids))
    assert body["steps"][0]["state"] == "completed"
    assert body["steps"][0]["completion_basis"] == "domain_fact"
    assert body["steps"][1]["evidence_summary"]["available"] is False
    assert body["readiness"]["can_close"] is True
    assert body["readiness"]["warning_count"] == 1
    assert body["freshness"]["available"] is True
    assert body["final_review"]["available"] is True
    assert [card["id"] for card in body["final_review"]["manual_review_cards"]] == [
        "cash",
        "deposits_savings",
        "debts_property",
        "income_budget",
        "investments_outside_integrations",
        "note",
    ]
    assert body["outlook"] is None
    assert body["links"]["close_readiness"].endswith(f"/api/months/{requested.id}/close-readiness")

    assert [older.status, requested.status] == before_month_statuses
    assert client.get("/api/months/999/close-workflow").status_code == 404


def test_closed_workflow_has_no_close_action_and_reopen_is_rederived(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    close_reporting_month(session, month.id)
    application = create_app(database)
    application.state.quote_preview_clock = lambda: TODAY
    client = TestClient(application)

    closed = client.get(f"/api/months/{month.id}/close-workflow").json()
    assert closed["month"]["id"] == month.id
    assert closed["month"]["status"] == "closed"
    assert closed["recommended_step_id"] == "next_month_outlook"
    closed_step_ids = [step["id"] for step in closed["steps"]]
    assert closed_step_ids == EXPECTED_WORKFLOW_STEP_IDS
    assert len(closed_step_ids) == len(set(closed_step_ids))
    assert [step["order"] for step in closed["steps"]] == list(range(1, 10))
    assert (
        next(step for step in closed["steps"] if step["id"] == "final_review_close")["state"]
        == "completed"
    )
    outlook_step = next(step for step in closed["steps"] if step["id"] == "next_month_outlook")
    assert outlook_step["state"] == "completed"
    assert outlook_step["primary_action"]["id"] == "open_cash_flow_ladder"
    assert closed["final_review"]["available"] is True
    assert closed["outlook"]["available"] is True
    assert closed["outlook"]["next_month"]["year"] == 2026
    assert closed["outlook"]["next_month"]["month"] == 2

    reopen_reporting_month(session, month.id)
    reopened = client.get(f"/api/months/{month.id}/close-workflow").json()
    assert reopened["month"]["status"] == "draft"
    assert reopened["month"]["id"] == month.id
    assert reopened["recommended_step_id"] == "alfa_baseline"
    assert reopened["outlook"] is None


def _workflow_step(client: TestClient, month_id: int, step_id: str) -> dict:
    response = client.get(f"/api/months/{month_id}/close-workflow")
    assert response.status_code == 200, response.text
    return next(step for step in response.json()["steps"] if step["id"] == step_id)


def _seed_baseline_evidence(session, month, snapshot: PositionSnapshot) -> None:
    applied = BrokerBaselineApply(
        provider="alfa_pro",
        reporting_month_id=month.id,
        baseline_date=month.snapshot_date,
        source_as_of=FETCHED_AT,
        captured_at=FETCHED_AT,
        confirmed_at=APPLIED_AT,
        apply_fingerprint="a" * 64,
    )
    session.add(applied)
    session.flush()
    session.add(
        BrokerBaselineApplyItem(
            reporting_month_id=month.id,
            baseline_apply_id=applied.id,
            position_snapshot_id=snapshot.id,
            action="unchanged",
            quantity=snapshot.quantity,
        )
    )
    session.commit()


def test_workflow_derives_alfa_selected_evidence_and_narrow_staleness(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    account = create_account(session, name="Alfa", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic share", instrument_type=InstrumentType.STOCK
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="2",
        average_cost_per_unit="100.00",
        market_price_per_unit="100.00",
        price_date=month.snapshot_date,
    )
    session.commit()
    _seed_baseline_evidence(session, month, snapshot)
    client = TestClient(create_app(database))

    completed = _workflow_step(client, month.id, "alfa_baseline")
    assert completed["state"] == "completed"
    assert completed["evidence_scope"] == "selected_rows_only"
    assert completed["evidence_summary"] == {
        "available": True,
        "coverage_scope": "selected_rows_only",
        "selected_count": 1,
        "matching_count": 1,
        "stale_count": 0,
    }

    stage_update_position_snapshot(session, snapshot.id, quantity="3")
    session.commit()
    quantity_changed = _workflow_step(client, month.id, "alfa_baseline")
    assert quantity_changed["state"] == "warning"
    assert "baseline_quantity_changed" in quantity_changed["reason_codes"]
    assert quantity_changed["stale"]["is_stale"] is True

    stage_update_position_snapshot(session, snapshot.id, quantity="2")
    month.snapshot_date = date(2031, 6, 30)
    session.commit()
    date_changed = _workflow_step(client, month.id, "alfa_baseline")
    assert date_changed["state"] == "warning"
    assert "baseline_date_changed" in date_changed["reason_codes"]


def test_workflow_keeps_quote_current_on_quantity_change_and_detects_remap(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic share", instrument_type=InstrumentType.STOCK
    )
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        price_date=TODAY,
    )
    _add_quote_provenance(session, snapshot, price_date=TODAY)
    session.add(
        InstrumentMarketMapping(
            instrument_id=instrument.id,
            provider=T_INVEST_PROVIDER,
            provider_instrument_id=STOCK_UID,
            provider_venue_id=None,
            excluded=False,
        )
    )
    session.commit()
    application = create_app(database)
    # Deterministic clock: quote freshness is evaluated against "today", so
    # pin it to the fixture date. Otherwise the test ages into a stale state
    # as the wall clock advances (same pattern as the neighbouring workflow
    # tests). Production semantics untouched.
    application.state.quote_preview_clock = lambda: TODAY
    client = TestClient(application)

    completed = _workflow_step(client, month.id, "market_quotes")
    assert completed["state"] == "completed"
    assert completed["evidence_scope"] == "full_current_local_scope"

    stage_update_position_snapshot(session, snapshot.id, quantity="2")
    session.commit()
    after_quantity_change = _workflow_step(client, month.id, "market_quotes")
    assert after_quantity_change["state"] == "completed"
    assert "quote_stale" not in after_quantity_change["reason_codes"]

    mapping = session.get(InstrumentMarketMapping, instrument.id)
    assert mapping is not None
    mapping.provider_instrument_id = BOND_UID
    session.commit()
    after_remap = _workflow_step(client, month.id, "market_quotes")
    assert after_remap["state"] == "warning"
    assert "quote_mapping_missing" in after_remap["reason_codes"]
    assert after_remap["evidence_summary"]["mapping_mismatch_count"] == 1


def _seed_statement_evidence(session, month, account_id: int, instrument_id: int):
    flow = create_investment_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type="coupon",
        event_date=date(month.year, month.month, 15),
        gross_amount="100.00",
        tax_amount="0.00",
        commission_amount="0.00",
        net_amount="100.00",
        source=ALFA_DEPOSITORY_INCOME_PROVIDER,
    )
    event = create_applied_statement_event(
        session,
        provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
        account_id=account_id,
        instrument_id=instrument_id,
        event_kind="coupon",
        isin="RU000A000000",
        record_date=date(month.year, month.month, 10),
        natural_identity="synthetic-statement-event",
        material_fingerprint="b" * 64,
        investment_cash_flow_id=flow.id,
        document_sha256="c" * 64,
        link_mode=StatementLinkMode.STATEMENT_CREATED,
        event_date=flow.event_date,
        quantity=Decimal("1"),
        per_unit=Decimal("100"),
        gross_amount_kopecks=10_000,
        gross_currency="RUB",
        tax_available=False,
        tax_amount_kopecks=None,
        tax_rate=None,
        net_amount_kopecks=10_000,
        net_currency="RUB",
        applied_at=APPLIED_AT,
    )
    session.commit()
    return flow, event


def test_workflow_derives_statement_link_and_retraction_evidence(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic bond", instrument_type=InstrumentType.BOND
    )
    flow, event = _seed_statement_evidence(session, month, account.id, instrument.id)
    client = TestClient(create_app(database))

    completed = _workflow_step(client, month.id, "actual_payouts")
    assert completed["state"] == "completed"
    assert completed["evidence_scope"] == "selected_rows_only"

    flow.gross_amount_kopecks = 20_000
    flow.net_amount_kopecks = 20_000
    session.commit()
    changed = _workflow_step(client, month.id, "actual_payouts")
    assert changed["state"] == "warning"
    assert "statement_linked_flow_changed" in changed["reason_codes"]

    retract_applied_statement_event(session, event.id, retracted_at=APPLIED_AT)
    session.commit()
    retracted = _workflow_step(client, month.id, "actual_payouts")
    assert retracted["state"] == "warning"
    assert "statement_rows_retracted" in retracted["reason_codes"]
    assert retracted["evidence_summary"]["matching_count"] == 0


def test_workflow_does_not_skip_unmapped_position_without_payout_evidence(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Unmapped synthetic bond", instrument_type=InstrumentType.BOND
    )
    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="3",
        average_cost_per_unit="100.00",
        market_price_per_unit="100.00",
        price_date=month.snapshot_date,
    )
    session.commit()
    client = TestClient(
        create_app(
            database,
            market_data_provider=_FailIfCalledProvider(),
            payout_provider=_FailIfCalledProvider(),
            broker_snapshot_provider=_FailIfCalledProvider(),
        )
    )

    unmapped = _workflow_step(client, month.id, "future_payouts")
    assert unmapped["state"] == "warning"
    assert unmapped["reason_codes"] == ["no_payout_eligible_positions"]
    assert unmapped["primary_action"]["id"] == "open_payout_batch_preview"

    session.add(
        InstrumentMarketMapping(
            instrument_id=instrument.id,
            provider=None,
            provider_instrument_id=None,
            provider_venue_id=None,
            excluded=True,
        )
    )
    session.commit()
    excluded = _workflow_step(client, month.id, "future_payouts")
    assert excluded["state"] == "skipped"


def test_workflow_derives_future_payout_dependencies_without_provider_calls(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic bond", instrument_type=InstrumentType.BOND
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="3",
        average_cost_per_unit="100.00",
        market_price_per_unit="100.00",
        price_date=month.snapshot_date,
    )
    session.add(
        InstrumentMarketMapping(
            instrument_id=instrument.id,
            provider=T_INVEST_PROVIDER,
            provider_instrument_id=BOND_UID,
            provider_venue_id=None,
            excluded=False,
        )
    )
    session.commit()
    payout = create_applied_payout(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        source_position_snapshot_id=snapshot.id,
        provider=T_INVEST_PROVIDER,
        provider_instrument_uid=BOND_UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key="synthetic-payout",
        payment_date=date(2031, 6, 15),
        per_unit_amount=Decimal("35.40"),
        currency="RUB",
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )
    session.commit()
    manual = create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2031, 6, 15),
        gross_amount="106.20",
        expected_tax_amount="0.00",
        expected_net_amount="106.20",
        source="synthetic calendar",
        source_as_of_date=month.snapshot_date,
        forecast_version="v1",
    )
    set_applied_payout_reconciliation(
        session,
        payout.id,
        expected_cash_flow_id=manual.id,
        counting_decision=PayoutCountingDecision.COUNT_PROVIDER,
    )
    session.commit()
    client = TestClient(
        create_app(
            database,
            market_data_provider=_FailIfCalledProvider(),
            payout_provider=_FailIfCalledProvider(),
            broker_snapshot_provider=_FailIfCalledProvider(),
        )
    )

    completed = _workflow_step(client, month.id, "future_payouts")
    assert completed["state"] == "completed"
    assert completed["evidence_scope"] == "selected_rows_only"

    other_account = create_account(session, name="Other broker", account_type=AccountType.BROKERAGE)
    other_instrument = create_instrument(
        session, name="Other synthetic bond", instrument_type=InstrumentType.BOND
    )
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=other_account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2031, 6, 15),
        gross_amount="106.20",
        expected_tax_amount="0.00",
        expected_net_amount="106.20",
        source="unrelated account calendar",
        source_as_of_date=month.snapshot_date,
        forecast_version="v1",
    )
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=other_instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2031, 6, 15),
        gross_amount="106.20",
        expected_tax_amount="0.00",
        expected_net_amount="106.20",
        source="unrelated instrument calendar",
        source_as_of_date=month.snapshot_date,
        forecast_version="v1",
    )
    session.commit()
    unrelated_scope = _workflow_step(client, month.id, "future_payouts")
    assert unrelated_scope["state"] == "completed"

    stage_update_position_snapshot(session, snapshot.id, quantity="4")
    session.commit()
    quantity_changed = _workflow_step(client, month.id, "future_payouts")
    assert quantity_changed["state"] == "warning"
    assert "payout_quantity_changed" in quantity_changed["reason_codes"]

    stage_update_position_snapshot(session, snapshot.id, quantity="3")
    mapping = session.get(InstrumentMarketMapping, instrument.id)
    assert mapping is not None
    mapping.provider_instrument_id = STOCK_UID
    session.commit()
    mapping_changed = _workflow_step(client, month.id, "future_payouts")
    assert mapping_changed["state"] == "warning"
    assert "payout_mapping_changed" in mapping_changed["reason_codes"]
    assert payout.total_amount_kopecks == 10_620

    mapping.provider_instrument_id = BOND_UID
    manual.expected_date = date(2031, 8, 1)
    session.commit()
    moved_target = _workflow_step(client, month.id, "future_payouts")
    assert moved_target["state"] == "warning"
    assert "payout_reconciliation_changed" in moved_target["reason_codes"]

    manual.expected_date = date(2031, 6, 15)
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2031, 6, 16),
        gross_amount="106.20",
        expected_tax_amount="0.00",
        expected_net_amount="106.20",
        source="another synthetic calendar",
        source_as_of_date=month.snapshot_date,
        forecast_version="v2",
    )
    duplicate_target = _workflow_step(client, month.id, "future_payouts")
    assert duplicate_target["state"] == "warning"
    assert "payout_reconciliation_changed" in duplicate_target["reason_codes"]


def test_final_review_reuses_dashboard_authorities_and_keeps_optional_cards_explicit(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2031, month=5, snapshot_date=date(2031, 5, 31))
    client = TestClient(
        create_app(
            database,
            market_data_provider=_FailIfCalledProvider(),
            payout_provider=_FailIfCalledProvider(),
            broker_snapshot_provider=_FailIfCalledProvider(),
        )
    )

    workflow = client.get(f"/api/months/{month.id}/close-workflow")
    dashboard = client.get(f"/api/months/{month.id}/dashboard")
    assert workflow.status_code == dashboard.status_code == 200
    workflow_body = workflow.json()
    dashboard_body = dashboard.json()

    final_review = workflow_body["final_review"]
    assert final_review["kpis"] == dashboard_body["kpis"]
    assert (
        final_review["actual_passive_income"] == dashboard_body["summary"]["passive_income_actual"]
    )
    assert final_review["important_future_events"]["available"] is True
    assert final_review["important_future_events"]["next_month"]["has_known_events"] is False
    assert final_review["important_future_events"]["next_month"]["passive_income"] is None
    assert final_review["investments"]["available"] is False
    assert final_review["investments"]["reason_code"] == "no_position_snapshots"
    assert final_review["reconciliation_availability"] == {
        "available": False,
        "reason_code": "reconciliation_not_run",
    }


def test_closed_outlook_uses_next_calendar_month_and_separates_redemption_principal(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=date(2026, 8, 31))
    account = create_account(session, name="Synthetic broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic bond", instrument_type=InstrumentType.BOND
    )
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.REDEMPTION,
        expected_date=date(2026, 9, 15),
        gross_amount="1234.56",
        expected_tax_amount="0.00",
        expected_net_amount="1234.56",
        source="synthetic calendar",
        source_as_of_date=month.snapshot_date,
        forecast_version="v1",
    )
    session.commit()
    close_reporting_month(session, month.id)
    before_month_count = session.scalar(select(func.count()).select_from(type(month)))
    before_flow_count = session.scalar(select(func.count()).select_from(ExpectedCashFlow))

    client = TestClient(
        create_app(
            database,
            market_data_provider=_FailIfCalledProvider(),
            payout_provider=_FailIfCalledProvider(),
            broker_snapshot_provider=_FailIfCalledProvider(),
        )
    )
    body = client.get(f"/api/months/{month.id}/close-workflow").json()
    outlook = body["outlook"]
    bucket = outlook["next_month"]
    assert outlook["available"] is True
    assert outlook["reason_code"] is None
    assert (bucket["year"], bucket["month"]) == (2026, 9)
    assert bucket["known_event_count"] == 1
    assert bucket["passive_income"] == {"amount": "0.00", "currency": "RUB"}
    assert bucket["redemption_principal"] == {"amount": "1234.56", "currency": "RUB"}
    assert bucket["total_cash_flow"] == {"amount": "1234.56", "currency": "RUB"}
    assert session.scalar(select(func.count()).select_from(type(month))) == before_month_count
    assert session.scalar(select(func.count()).select_from(ExpectedCashFlow)) == before_flow_count
