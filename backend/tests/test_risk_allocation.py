"""R07-06A persisted-data allocation and concentration contract tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.domain.risk_allocation import RiskSupportStatus
from hermes_finance.main import create_app
from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    PayoutCountingDecision,
    create_applied_payout,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.risk_allocation import risk_allocation_for_month

APPLIED_AT = datetime(2030, 5, 12, 12, 0, tzinfo=UTC)
PROVIDER_UID = "synthetic-instrument-uid"


@pytest.fixture
def session(tmp_path: Path) -> Generator[Session, None, None]:
    database = create_database(tmp_path / "risk-allocation.db")
    Base.metadata.create_all(database.engine)
    db_session = database.session_factory()
    try:
        yield db_session
    finally:
        db_session.close()
        database.engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "risk-allocation-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _month(session: Session) -> object:
    return create_reporting_month(
        session,
        year=2030,
        month=5,
        snapshot_date=date(2030, 5, 12),
    )


def _position(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    amount: str,
    quantity: str = "1",
) -> object:
    return create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        average_cost_per_unit="1.00",
        market_price_per_unit=amount,
        price_date=date(2030, 5, 12),
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
    currency: str = "RUB",
) -> object:
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        expected_date=expected_date,
        gross_amount=amount,
        currency=currency,
        source="synthetic owner forecast",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )


def test_empty_month_is_explicit_and_api_serializable(client: TestClient) -> None:
    created = client.post(
        "/api/months",
        json={"year": 2030, "month": 5, "snapshot_date": "2030-05-12"},
    )
    assert created.status_code == 201, created.text
    month_id = created.json()["id"]

    response = client.get(f"/api/analytics/risk-allocation?month_id={month_id}&top_n=2")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reporting_month_id"] == month_id
    assert body["as_of_date"] == "2030-05-12"
    assert body["base_currency"] == "RUB"
    assert body["liquid_assets_total"] == {"amount": "0.00", "currency": "RUB"}
    assert body["allocation_by_asset_class"]["items"] == []
    assert body["allocation_by_asset_class"]["coverage_pct"] is None
    assert body["allocation_by_account"]["items"] == []
    assert body["top_positions"]["items"] == []
    assert body["payout_concentration"]["top_share_pct"] is None
    assert body["redemption_concentration"]["top_share_pct"] is None
    assert body["support"]["issuer"] == {
        "status": "unavailable",
        "reason_codes": ["issuer_not_persisted"],
    }
    assert body["support"]["maturity"] == {
        "status": "unavailable",
        "reason_codes": ["maturity_not_persisted"],
    }


def test_api_serializes_exact_amounts_and_decimal_percentages(client: TestClient) -> None:
    account = client.post(
        "/api/accounts",
        json={"name": "Synthetic API account", "account_type": "brokerage"},
    )
    assert account.status_code == 201, account.text
    instrument = client.post(
        "/api/instruments",
        json={"name": "Synthetic API stock", "instrument_type": "stock"},
    )
    assert instrument.status_code == 201, instrument.text
    month = client.post(
        "/api/months",
        json={"year": 2030, "month": 5, "snapshot_date": "2030-05-12"},
    )
    assert month.status_code == 201, month.text
    month_id = month.json()["id"]
    position = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": account.json()["id"],
            "instrument_id": instrument.json()["id"],
            "quantity": "1",
            "average_cost_per_unit": {"amount": "1.00", "currency": "RUB"},
            "market_price_per_unit": {"amount": "123.45", "currency": "RUB"},
            "price_date": "2030-05-12",
        },
    )
    assert position.status_code == 201, position.text

    response = client.get(f"/api/analytics/risk-allocation?month_id={month_id}&top_n=1")

    assert response.status_code == 200, response.text
    body = response.json()
    asset = body["allocation_by_asset_class"]["items"][0]
    assert asset["key"] == "stock"
    assert asset["instrument_type"] == "stock"
    assert asset["amount"] == {"amount": "123.45", "currency": "RUB"}
    assert asset["share_pct"] == "100.00"
    account_item = body["allocation_by_account"]["items"][0]
    assert account_item["label"] == "Synthetic API account"
    assert account_item["share_pct"] == "100.00"
    assert body["top_positions"]["top_amount"] == {
        "amount": "123.45",
        "currency": "RUB",
    }
    assert body["top_positions"]["top_share_pct"] == "100.00"


def test_allocation_uses_explicit_types_accounts_and_deterministic_top_n(
    session: Session,
) -> None:
    month = _month(session)
    account_a = create_account(
        session,
        name="Synthetic Broker A",
        account_type=AccountType.BROKERAGE,
    )
    account_b = create_account(
        session,
        name="Synthetic Broker B",
        account_type=AccountType.IIS,
    )
    stock = create_instrument(session, name="Synthetic stock", instrument_type=InstrumentType.STOCK)
    bond = create_instrument(session, name="Synthetic bond", instrument_type=InstrumentType.BOND)
    gold = create_instrument(session, name="Synthetic gold", instrument_type=InstrumentType.GOLD)
    fund = create_instrument(session, name="Synthetic fund", instrument_type=InstrumentType.FUND)

    stock_position = _position(
        session,
        month_id=month.id,
        account_id=account_a.id,
        instrument_id=stock.id,
        amount="1000.00",
    )
    bond_position = _position(
        session,
        month_id=month.id,
        account_id=account_b.id,
        instrument_id=bond.id,
        amount="3000.00",
    )
    gold_position = _position(
        session,
        month_id=month.id,
        account_id=account_a.id,
        instrument_id=gold.id,
        amount="2000.00",
    )
    _position(
        session,
        month_id=month.id,
        account_id=account_a.id,
        instrument_id=fund.id,
        amount="2000.00",
    )
    create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account_b.id,
        name="Synthetic deposit",
        deposit_type="deposit",
        balance="500.00",
        annual_rate="0.00",
    )
    create_cash_balance(
        session,
        reporting_month_id=month.id,
        name="Unassigned synthetic cash",
        amount="250.00",
    )

    result = risk_allocation_for_month(session, month.id, top_n=2)

    assert result.liquid_assets_total.kopecks == 875_000
    assert [item.key for item in result.allocation_by_asset_class.items] == [
        "bond",
        "fund",
        "gold",
        "stock",
        "deposits",
        "cash",
    ]
    asset_items = {item.key: item for item in result.allocation_by_asset_class.items}
    assert asset_items["fund"].instrument_type == "fund"
    assert asset_items["gold"].instrument_type == "gold"
    assert asset_items["fund"].share_pct == asset_items["gold"].share_pct
    assert asset_items["bond"].share_pct == result.allocation_by_asset_class.items[0].share_pct

    account_items = {item.key: item for item in result.allocation_by_account.items}
    assert account_items[f"account:{account_a.id}"].label == account_a.name
    assert account_items[f"account:{account_a.id}"].amount.kopecks == 500_000
    assert account_items[f"account:{account_b.id}"].amount.kopecks == 350_000
    assert account_items["unassigned_cash"].amount.kopecks == 25_000
    assert result.allocation_by_account.covered_amount.kopecks == 850_000
    assert result.allocation_by_account.unallocated_amount.kopecks == 25_000
    assert result.allocation_by_account.coverage_pct == Decimal("97.14")

    assert [item.position_id for item in result.top_positions.items] == [
        bond_position.id,
        gold_position.id,
    ]
    assert result.top_positions.top_amount.kopecks == 500_000
    assert result.top_positions.top_share_pct == Decimal("57.14")
    assert result.top_positions.support.status is RiskSupportStatus.SUPPORTED
    assert stock_position.id not in [item.position_id for item in result.top_positions.items]


def test_missing_and_foreign_currency_are_not_guessed_or_included(session: Session) -> None:
    month = _month(session)
    account = create_account(
        session,
        name="Synthetic account",
        account_type=AccountType.BROKERAGE,
    )
    missing_currency = create_instrument(
        session,
        name="Instrument named USD but currency missing",
        instrument_type=InstrumentType.STOCK,
    )
    foreign_currency = create_instrument(
        session,
        name="Synthetic foreign instrument",
        instrument_type=InstrumentType.BOND,
        currency="USD",
    )
    missing_currency.currency = ""
    session.commit()
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=missing_currency.id,
        amount="1000.00",
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=foreign_currency.id,
        amount="2000.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=foreign_currency.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2030, 5, 13),
        amount="100.00",
        currency="USD",
    )

    result = risk_allocation_for_month(session, month.id)

    assert result.liquid_assets_total.kopecks == 0
    assert result.allocation_by_asset_class.items == ()
    assert result.allocation_by_account.items == ()
    assert result.top_positions.items == ()
    assert result.allocation_by_asset_class.support.status is RiskSupportStatus.UNAVAILABLE
    assert result.allocation_by_asset_class.support.reason_codes == (
        "currency_conversion_not_supported",
        "currency_not_persisted",
    )
    assert result.support["currency"].status is RiskSupportStatus.UNAVAILABLE
    assert result.support["currency"].reason_codes == (
        "currency_conversion_not_supported",
        "currency_not_persisted",
    )
    assert result.payout_concentration.support.status is RiskSupportStatus.UNAVAILABLE
    assert "no_dated_payouts" not in result.payout_concentration.support.reason_codes
    assert result.support["issuer"].status is RiskSupportStatus.UNAVAILABLE
    assert result.support["maturity"].status is RiskSupportStatus.UNAVAILABLE


def test_payout_and_redemption_concentration_uses_dated_ladder_semantics(
    session: Session,
) -> None:
    month = _month(session)
    account = create_account(
        session,
        name="Synthetic payout account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic payout instrument",
        instrument_type=InstrumentType.BOND,
    )
    _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        amount="100.00",
    )
    create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Undated synthetic deposit",
        deposit_type="deposit",
        balance="1000.00",
        annual_rate="12.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2030, 5, 13),
        amount="100.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.INTEREST,
        expected_date=date(2030, 6, 1),
        amount="50.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.OTHER,
        expected_date=date(2030, 7, 1),
        amount="25.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.REDEMPTION,
        expected_date=date(2030, 8, 1),
        amount="1000.00",
    )
    _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2031, 5, 12),
        amount="9000.00",
    )

    result = risk_allocation_for_month(session, month.id)

    assert result.payout_concentration.denominator.kopecks == 17_500
    assert result.payout_concentration.items[0].amount.kopecks == 17_500
    assert result.payout_concentration.items[0].event_count == 3
    assert result.payout_concentration.items[0].is_approximate is True
    assert result.payout_concentration.support.status is RiskSupportStatus.SUPPORTED
    assert "deposit_forecast_not_concentratable" in (
        result.payout_concentration.support.reason_codes
    )
    assert result.redemption_concentration.denominator.kopecks == 100_000
    assert result.redemption_concentration.items[0].amount.kopecks == 100_000
    assert result.redemption_concentration.items[0].event_count == 1
    assert result.redemption_concentration.support.status is RiskSupportStatus.SUPPORTED
    assert result.payout_concentration.items[0].amount.kopecks != (
        result.redemption_concentration.items[0].amount.kopecks
    )


def test_unresolved_provider_duplicate_is_not_counted_until_accepted(session: Session) -> None:
    month = _month(session)
    account = create_account(
        session,
        name="Synthetic provider account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic provider instrument",
        instrument_type=InstrumentType.BOND,
    )
    position = _position(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        amount="100.00",
    )
    manual = _flow(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=date(2030, 6, 15),
        amount="100.00",
    )
    provider = create_applied_payout(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        source_position_snapshot_id=position.id,
        provider="synthetic_provider",
        provider_instrument_uid=PROVIDER_UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key="synthetic-event-1",
        payment_date=date(2030, 6, 15),
        per_unit_amount="50.00",
        currency="RUB",
        fetched_at=APPLIED_AT,
        applied_at=APPLIED_AT,
    )
    session.commit()

    unresolved = risk_allocation_for_month(session, month.id)

    assert unresolved.payout_concentration.denominator.kopecks == 10_000
    assert unresolved.payout_concentration.items[0].event_count == 1

    set_applied_payout_reconciliation(
        session,
        provider.id,
        expected_cash_flow_id=manual.id,
        counting_decision=PayoutCountingDecision.KEEP_BOTH,
    )
    session.commit()

    accepted = risk_allocation_for_month(session, month.id)

    assert accepted.payout_concentration.denominator.kopecks == 15_000
    assert accepted.payout_concentration.items[0].event_count == 2
    assert accepted.payout_concentration.is_approximate is True
