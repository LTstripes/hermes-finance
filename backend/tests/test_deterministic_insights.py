"""Synthetic contract tests for the R07-11A deterministic insights engine."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExpectedCashFlowType,
    IncomeType,
    InstrumentType,
    PriceSource,
)
from hermes_finance.domain.risk_allocation import RiskSupportStatus
from hermes_finance.main import create_app
from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.persistence import Base, PositionQuoteProvenance, ReportingMonth
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import create_applied_payout
from hermes_finance.services.close_readiness import CloseReadinessCode
from hermes_finance.services.deterministic_insights import (
    CONCENTRATION_THRESHOLD_PCT,
    DeterministicInsight,
    DeterministicInsightsResult,
    InsightPeriod,
    InsightProvenance,
    InsightSeverity,
    build_deterministic_insights,
)
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import apply_snapshot_market_quote, create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

TODAY = date(2030, 5, 12)
FETCHED_AT = datetime(2030, 4, 1, 10, 0, tzinfo=UTC)
APPLIED_AT = datetime(2030, 4, 2, 11, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session, None, None]:
    database = create_database(tmp_path / "deterministic-insights.db")
    Base.metadata.create_all(database.engine)
    db_session = database.session_factory()
    try:
        yield db_session
    finally:
        db_session.close()
        database.engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "deterministic-insights-api.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


@contextmanager
def _forbid_sql_writes(engine: Engine) -> Iterator[None]:
    write_verbs = {"INSERT", "UPDATE", "DELETE", "REPLACE"}

    def _before_cursor_execute(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb in write_verbs:
            raise AssertionError(f"insights issued persistence write: {statement[:240]}")

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def _month(session: Session, *, year: int = 2030, month: int = 5):
    return create_reporting_month(
        session,
        year=year,
        month=month,
        snapshot_date=date(year, month, 12),
    )


def _position(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    amount: str,
    price_source: PriceSource | str = PriceSource.MANUAL,
    price_date: date = TODAY,
):
    return create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity="1",
        average_cost_per_unit=amount,
        market_price_per_unit=amount,
        price_date=price_date,
        price_source=price_source,
    )


def _flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: ExpectedCashFlowType,
    expected_date: date,
    amount: str,
    source_as_of_date: date = TODAY,
):
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        expected_date=expected_date,
        gross_amount=amount,
        currency="RUB",
        source="synthetic owner forecast",
        source_as_of_date=source_as_of_date,
        forecast_version="v1",
    )


def _codes(result) -> list[str]:
    return [item.code for item in result.insights]


def test_empty_month_has_no_signal(session: Session) -> None:
    month = _month(session, year=2030, month=1)

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)

    assert result.insights == ()


def test_missing_active_capital_account_snapshot_is_actionable_coverage_warning(
    session: Session,
) -> None:
    month = _month(session)
    create_account(
        session,
        name="Synthetic missing snapshot account",
        account_type=AccountType.BROKERAGE,
    )

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)

    insight = next(
        item for item in result.insights if item.code == "active_account_snapshot_missing"
    )
    assert insight.type == "data_quality"
    assert insight.severity is InsightSeverity.WARNING
    assert insight.evidence == {
        "close_readiness_code": "active_account_snapshot_missing",
        "close_readiness_severity": "warning",
        "can_close": True,
        "status": "draft",
        "snapshot_date": "2030-05-12",
        "context": {
            "account_names": ["Synthetic missing snapshot account"],
            "count": 1,
        },
    }
    assert insight.reason == "close_readiness_reported_missing_active_account_snapshot"


def test_present_active_capital_account_snapshot_suppresses_coverage_warning(
    session: Session,
) -> None:
    month = _month(session)
    account = create_account(
        session,
        name="Synthetic covered account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic covered instrument",
        instrument_type=InstrumentType.STOCK,
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        amount="100.00",
    )

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)

    assert "active_account_snapshot_missing" not in _codes(result)


def test_concentration_rules_emit_exact_evidence(session: Session) -> None:
    month = _month(session)
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    bond = create_instrument(session, name="Synthetic bond", instrument_type=InstrumentType.BOND)
    stock = create_instrument(session, name="Synthetic stock", instrument_type=InstrumentType.STOCK)
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        amount="600.00",
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        amount="400.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2030, 6, 1),
        amount="7000.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        flow_type=ExpectedCashFlowType.DIVIDEND,
        expected_date=date(2030, 7, 1),
        amount="3000.00",
    )

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)
    by_code = {item.code: item for item in result.insights}

    assert by_code["portfolio_concentration"].severity is InsightSeverity.WARNING
    assert by_code["portfolio_concentration"].evidence["top_share_pct"] == "60.00"
    assert by_code["portfolio_concentration"].evidence["threshold_pct"] == format(
        CONCENTRATION_THRESHOLD_PCT, "f"
    )
    assert by_code["upcoming_payout_concentration"].evidence["top_share_pct"] == "70.00"
    assert "redemption_concentration" not in by_code
    assert "partial_asset_class_coverage" not in by_code
    assert all(item.comparison_period is None for item in result.insights)


def test_redemption_concentration_is_separate_from_payouts(session: Session) -> None:
    month = _month(session)
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    bond = create_instrument(session, name="Synthetic bond", instrument_type=InstrumentType.BOND)
    other = create_instrument(session, name="Synthetic other", instrument_type=InstrumentType.OTHER)
    bond_position = _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        amount="100.00",
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=other.id,
        amount="100.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        flow_type=ExpectedCashFlowType.REDEMPTION,
        expected_date=date(2030, 6, 1),
        amount="10000.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=other.id,
        flow_type=ExpectedCashFlowType.REDEMPTION,
        expected_date=date(2030, 7, 1),
        amount="100.00",
    )

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)
    by_code = {item.code: item for item in result.insights}

    assert by_code["redemption_concentration"].evidence["top_share_pct"] == "99.01"
    assert "upcoming_payout_concentration" not in by_code
    assert by_code["redemption_concentration"].evidence["top_amount"] == {
        "amount": "10000.00",
        "currency": "RUB",
    }
    assert bond_position.id > 0


def test_partial_asset_class_coverage_is_explicit_and_not_guessed(session: Session) -> None:
    month = _month(session)
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    known = create_instrument(session, name="Synthetic stock", instrument_type=InstrumentType.STOCK)
    unknown = create_instrument(
        session, name="Synthetic legacy", instrument_type=InstrumentType.BOND
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=known.id,
        amount="400.00",
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=unknown.id,
        amount="600.00",
    )
    session.execute(text("PRAGMA ignore_check_constraints = ON"))
    session.execute(
        text("UPDATE instruments SET instrument_type = :value WHERE id = :instrument_id"),
        {"value": "legacy-unknown", "instrument_id": unknown.id},
    )
    session.commit()
    session.execute(text("PRAGMA ignore_check_constraints = OFF"))

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)
    by_code = {item.code: item for item in result.insights}
    insight = by_code["partial_asset_class_coverage"]

    assert insight.severity is InsightSeverity.INFO
    assert insight.evidence["coverage_pct"] == "40.00"
    assert insight.evidence["unallocated_amount"] == {
        "amount": "600.00",
        "currency": "RUB",
    }
    assert insight.evidence["support_status"] == RiskSupportStatus.UNKNOWN.value
    assert "instrument_type_not_authoritative" in insight.evidence["support_reason_codes"]


def test_freshness_tax_and_payout_reconciliation_rules_are_explainable(session: Session) -> None:
    month = _month(session, year=2031, month=5)
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    bond = create_instrument(session, name="Synthetic bond", instrument_type=InstrumentType.BOND)
    snapshot = _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        amount="100.00",
        price_source=PriceSource.MANUAL,
        price_date=date(2030, 1, 1),
    )
    apply_snapshot_market_quote(
        session,
        snapshot,
        market_price_per_unit_kopecks=10_000,
        price_date=date(2030, 1, 1),
        price_source=PriceSource.T_INVEST,
    )
    session.add(
        PositionQuoteProvenance(
            position_snapshot_id=snapshot.id,
            reporting_month_id=month.id,
            provider="t_invest",
            provider_instrument_id="synthetic-instrument",
            provider_venue_id=None,
            quote_kind="last",
            raw_price="100.00",
            raw_price_basis="R",
            normalized_price_kopecks=10_000,
            price_date=date(2030, 1, 1),
            fetched_at_utc=FETCHED_AT,
            target_date=date(2031, 5, 12),
            freshness="stale",
            applied_at_utc=APPLIED_AT,
        )
    )
    session.commit()
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type=IncomeType.SALARY,
        name="Synthetic salary",
        gross_amount="100000.00",
        tax_amount="13000.00",
        net_amount="87000.00",
    )
    provider_payout = create_applied_payout(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        source_position_snapshot_id=snapshot.id,
        provider="t_invest",
        provider_instrument_uid="synthetic-instrument",
        event_kind=PayoutEventKind.COUPON,
        identity_key="synthetic-payout",
        payment_date=date(2031, 6, 1),
        per_unit_amount=Decimal("20.00"),
        currency="RUB",
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2031, 6, 2),
        amount="20.00",
        source_as_of_date=date(2031, 5, 12),
    )
    session.commit()

    result = build_deterministic_insights(
        session,
        month.id,
        evaluated_on=date(2031, 5, 12),
    )
    by_code = {item.code: item for item in result.insights}

    assert "quote_unavailable" in by_code
    assert by_code["quote_unavailable"].type == "freshness_warning"
    assert by_code["quote_unavailable"].evidence["family_id"] == "market_quotes"
    assert by_code["unresolved_payout_reconciliation"].evidence["count"] == 1
    assert by_code["salary_tax_history_incomplete"].evidence["taxable_gross_ytd"] is None
    assert by_code["salary_tax_history_incomplete"].severity is InsightSeverity.WARNING
    assert provider_payout.id > 0


def test_missing_snapshot_suppresses_all_other_rules(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    month = SimpleNamespace(
        id=1,
        year=2030,
        month=6,
        snapshot_date=None,
        status="draft",
    )
    monkeypatch.setattr(
        "hermes_finance.services.deterministic_insights.get_reporting_month",
        lambda _session, _month_id: month,
    )

    result = build_deterministic_insights(session, month.id, evaluated_on=TODAY)

    assert _codes(result) == [CloseReadinessCode.SNAPSHOT_DATE_REQUIRED.value]
    assert result.insights[0].severity is InsightSeverity.ERROR
    assert result.insights[0].evidence["snapshot_date"] is None


def test_service_is_deterministic_read_only_and_api_serializes_contract(
    session: Session,
    client: TestClient,
) -> None:
    month = _month(session, year=2030, month=1)
    before_status = session.scalar(
        select(ReportingMonth.status).where(ReportingMonth.id == month.id)
    )

    with _forbid_sql_writes(session.get_bind()):
        first = build_deterministic_insights(session, month.id, evaluated_on=TODAY)
        second = build_deterministic_insights(session, month.id, evaluated_on=TODAY)

    assert first == second
    assert session.scalar(select(ReportingMonth.status).where(ReportingMonth.id == month.id)) == (
        before_status
    )

    created = client.post(
        "/api/months",
        json={"year": 2030, "month": 1, "snapshot_date": "2030-01-31"},
    )
    assert created.status_code == 201, created.text
    response = client.get(f"/api/months/{created.json()['id']}/deterministic-insights")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract_version"] == "deterministic_insights_v1"
    assert body["ruleset_version"] == "v1"
    assert body["forecast_version"] == "v1"
    assert body["snapshot_date"] == "2030-01-31"
    assert body["insights"] == []


def test_api_serializes_structured_insight_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = DeterministicInsightsResult(
        contract_version="deterministic_insights_v1",
        ruleset_version="v1",
        forecast_version="v1",
        reporting_month_id=7,
        year=2030,
        month=5,
        status="draft",
        snapshot_date=date(2030, 5, 12),
        evaluated_on=TODAY,
        insights=(
            DeterministicInsight(
                code="synthetic_rule",
                type="synthetic",
                severity=InsightSeverity.INFO,
                message="Synthetic evidence is available.",
                evidence={"amount": {"amount": "10.00", "currency": "RUB"}},
                comparison_period=InsightPeriod(year=2030, month=4),
                source="synthetic_source",
                as_of=date(2030, 5, 12),
                provenance=(
                    InsightProvenance(
                        source="synthetic_source",
                        provider="synthetic_provider",
                        observed_at=date(2030, 5, 11),
                    ),
                ),
                reason="synthetic_value_is_present",
            ),
        ),
    )
    monkeypatch.setattr(
        "hermes_finance.api.deterministic_insights.build_deterministic_insights",
        lambda *_args, **_kwargs: result,
    )

    response = client.get("/api/months/7/deterministic-insights")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "contract_version": "deterministic_insights_v1",
        "ruleset_version": "v1",
        "forecast_version": "v1",
        "reporting_month_id": 7,
        "year": 2030,
        "month": 5,
        "status": "draft",
        "snapshot_date": "2030-05-12",
        "evaluated_on": "2030-05-12",
        "insights": [
            {
                "code": "synthetic_rule",
                "type": "synthetic",
                "severity": "info",
                "message": "Synthetic evidence is available.",
                "evidence": {"amount": {"amount": "10.00", "currency": "RUB"}},
                "comparison_period": {"year": 2030, "month": 4},
                "source": "synthetic_source",
                "as_of": "2030-05-12",
                "provenance": [
                    {
                        "source": "synthetic_source",
                        "provider": "synthetic_provider",
                        "observed_at": "2030-05-11",
                    }
                ],
                "reason": "synthetic_value_is_present",
            }
        ],
    }
