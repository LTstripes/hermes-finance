"""R07-07 freshness/provenance summary semantics."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from t_invest_mapping_fixtures import accept_t_invest_mapping

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DepositType,
    ExpenseType,
    IncomeType,
    InstrumentType,
    InvestmentCashFlowType,
    PriceSource,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, PositionQuoteProvenance, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import create_applied_payout
from hermes_finance.services.applied_statement_events import (
    StatementLinkMode,
    create_applied_statement_event,
)
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expenses import create_expense_entry
from hermes_finance.services.freshness_provenance import (
    FreshnessFamilyId,
    FreshnessReasonCode,
    FreshnessStatus,
    SourceTimestampKind,
    build_freshness_provenance_summary,
)
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.positions import (
    apply_snapshot_market_quote,
    create_position_snapshot,
    update_position_snapshot,
)
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER

TODAY = date(2026, 8, 27)
SNAPSHOT_DATE = date(2026, 8, 31)
GENERATED_AT = datetime(2026, 8, 27, 9, 30, tzinfo=timezone.utc)
FETCHED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
APPLIED_AT = datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
SHA = "ab" * 32


def session_for(tmp_path: Path):
    database = create_database(tmp_path / "freshness.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _family(summary, family_id: FreshnessFamilyId):
    return next(family for family in summary.families if family.family_id is family_id)


def _codes(summary) -> set[str]:
    return {reason.code.value for reason in summary.reasons}


def _seed_month(session):
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=SNAPSHOT_DATE)
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    deposit_account = create_account(session, name="Вклад", account_type=AccountType.DEPOSIT)
    stock = create_instrument(session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK)
    fund = create_instrument(session, name="Manual Fund", instrument_type=InstrumentType.FUND)
    return month, account, deposit_account, stock, fund


def _t_invest_snapshot(
    session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    price_date: date,
    quantity: str = "1",
    kopecks: int = 10000,
):
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
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
    applied_at: datetime = APPLIED_AT,
    fetched_at: datetime = FETCHED_AT,
    provider: str = "t_invest",
) -> None:
    session.add(
        PositionQuoteProvenance(
            position_snapshot_id=snapshot.id,
            reporting_month_id=snapshot.reporting_month_id,
            provider=provider,
            provider_instrument_id=STOCK_UID,
            provider_venue_id=None,
            quote_kind="last",
            raw_price="215.50",
            raw_price_basis="R",
            normalized_price_kopecks=21550,
            price_date=price_date,
            fetched_at_utc=fetched_at,
            target_date=price_date,
            freshness=freshness,
            applied_at_utc=applied_at,
        )
    )
    session.commit()


def test_empty_month_has_no_score_and_manual_is_not_stale(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, _account, _deposit_account, _stock, _fund = _seed_month(session)
    summary = build_freshness_provenance_summary(
        session, month.id, today=TODAY, generated_at=GENERATED_AT
    )
    payload = summary.families
    assert len(payload) == 6
    assert summary.reporting_month.snapshot_date == SNAPSHOT_DATE
    assert summary.quote_valuation_target_date == TODAY
    assert summary.evaluated_on == TODAY
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.MISSING
    assert quotes.coverage.stale_count == 0
    alfa = _family(summary, FreshnessFamilyId.ALFA_PRO_POSITIONS)
    assert alfa.status is FreshnessStatus.UNKNOWN
    assert alfa.providers == ()
    assert "alfa_pro" not in summary.providers
    assert FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_PERSISTED in {
        reason.code for reason in alfa.reasons
    }
    manual = _family(summary, FreshnessFamilyId.MANUAL_MONTH_DATA)
    assert manual.status is FreshnessStatus.MISSING
    assert all(reason.code is not FreshnessReasonCode.QUOTE_STALE for reason in summary.reasons)
    assert "freshness_score" not in summary.__dataclass_fields__
    assert "freshness_pct" not in summary.__dataclass_fields__


def test_manual_position_without_provider_timestamp_is_not_stale(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        quantity="10",
        average_cost_per_unit="200.00",
        market_price_per_unit="200.00",
        price_date=date(2026, 1, 1),
        price_source=PriceSource.MANUAL,
    )
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.NOT_APPLICABLE
    assert quotes.coverage.stale_count == 0
    assert quotes.coverage.manual_count == 1
    item = quotes.items[0]
    assert item.freshness_status is FreshnessStatus.NOT_APPLICABLE
    assert item.source_timestamp_kind is SourceTimestampKind.NOT_APPLICABLE
    assert item.source_date is None
    assert item.import_apply_time is None
    assert item.local_edit_time is not None
    assert item.local_edit_time.replace(tzinfo=None) == snapshot.updated_at.replace(tzinfo=None)
    assert FreshnessReasonCode.MANUAL_SOURCE_NO_PROVIDER_TIMESTAMP in item.reason_codes
    assert FreshnessReasonCode.QUOTE_STALE not in _codes(summary)


def test_stale_quote_uses_price_date_not_apply_time(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 8, 10),
        quantity="10",
        kopecks=21550,
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 8, 10), freshness="ok")
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.STALE
    item = quotes.items[0]
    assert item.freshness_status is FreshnessStatus.STALE
    assert item.source_date == date(2026, 8, 10)
    assert item.source_timestamp_kind is SourceTimestampKind.PRICE_DATE
    assert item.fetched_at == FETCHED_AT
    assert item.import_apply_time == APPLIED_AT
    assert item.import_apply_time.date() != item.source_date
    assert summary.reporting_month.snapshot_date != item.source_date
    assert FreshnessReasonCode.QUOTE_STALE in _codes(summary)


def test_current_and_stale_quotes_are_mixed_not_scored(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, fund = _seed_month(session)
    current = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 8, 25),
    )
    stale = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=fund.id,
        price_date=date(2026, 8, 10),
    )
    _add_quote_provenance(session, current, price_date=date(2026, 8, 25))
    _add_quote_provenance(session, stale, price_date=date(2026, 8, 10))
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.MIXED
    assert quotes.coverage.current_count == 1
    assert quotes.coverage.stale_count == 1
    assert quotes.coverage.row_count == 2


def test_quote_older_than_lookback_is_unavailable_not_missing_timestamp(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 7, 1),
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 7, 1), freshness="stale")
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.UNAVAILABLE
    assert quotes.items[0].source_date == date(2026, 7, 1)
    assert FreshnessReasonCode.QUOTE_UNAVAILABLE in _codes(summary)


def test_mapped_manual_quote_is_coverage_warning_not_stale(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    accept_t_invest_mapping(session, stock.id, STOCK_UID, kind=InstrumentType.STOCK)
    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        quantity="1",
        average_cost_per_unit="100.00",
        market_price_per_unit="100.00",
        price_date=date(2026, 8, 1),
        price_source=PriceSource.MANUAL,
    )
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.NOT_APPLICABLE
    assert quotes.coverage.missing_count == 1
    assert quotes.items[0].freshness_status is FreshnessStatus.NOT_APPLICABLE
    assert FreshnessReasonCode.MAPPED_QUOTE_NOT_APPLIED in _codes(summary)
    assert FreshnessReasonCode.QUOTE_STALE not in _codes(summary)


def test_manual_override_keeps_history_and_stops_quote_freshness(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 8, 10),
        kopecks=21550,
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 8, 10))
    update_position_snapshot(
        session,
        snapshot.id,
        price_source=PriceSource.MANUAL,
        market_price_per_unit="180.00",
        price_date=date(2026, 8, 27),
    )
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    item = quotes.items[0]
    assert item.source_kind == PriceSource.MANUAL.value
    assert item.freshness_status is FreshnessStatus.NOT_APPLICABLE
    assert FreshnessReasonCode.HISTORICAL_QUOTE_PROVENANCE_PRESENT in item.reason_codes
    assert item.import_apply_time == APPLIED_AT
    assert quotes.status is not FreshnessStatus.STALE


def test_t_invest_only_month_does_not_claim_alfa_pro_provider(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 8, 25),
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 8, 25))
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    alfa = _family(summary, FreshnessFamilyId.ALFA_PRO_POSITIONS)
    assert "alfa_pro" not in summary.providers
    assert alfa.providers == ()
    assert FreshnessReasonCode.MULTIPLE_PROVIDERS not in _codes(summary)
    assert set(summary.providers) == {"t_invest"}
    assert alfa.status is FreshnessStatus.UNKNOWN
    assert FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_PERSISTED in {
        reason.code for reason in alfa.reasons
    }


def test_payouts_and_statements_are_not_stale_by_event_age(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        quantity="3",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2026, 8, 1),
        price_source=PriceSource.MANUAL,
    )
    create_applied_payout(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        source_position_snapshot_id=snapshot.id,
        provider="t_invest",
        provider_instrument_uid=STOCK_UID,
        event_kind="coupon",
        identity_key="n:1",
        payment_date=date(2026, 6, 15),
        per_unit_amount=Decimal("10.000000000"),
        currency="RUB",
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )
    flow = create_investment_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        flow_type=InvestmentCashFlowType.COUPON,
        event_date=date(2026, 5, 1),
        gross_amount="100.00",
        net_amount="100.00",
        source=ALFA_DEPOSITORY_INCOME_PROVIDER,
    )
    create_applied_statement_event(
        session,
        provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
        account_id=account.id,
        instrument_id=stock.id,
        event_kind="coupon",
        isin="RU000A0JX0J0",
        record_date=date(2026, 4, 20),
        natural_identity="synthetic-identity",
        material_fingerprint=SHA,
        investment_cash_flow_id=flow.id,
        document_sha256=SHA,
        link_mode=StatementLinkMode.STATEMENT_CREATED,
        event_date=date(2026, 5, 1),
        quantity=Decimal("1"),
        per_unit=Decimal("100"),
        gross_amount_kopecks=10000,
        gross_currency="RUB",
        tax_available=False,
        tax_amount_kopecks=None,
        tax_rate=None,
        net_amount_kopecks=10000,
        net_currency="RUB",
        applied_at=APPLIED_AT,
    )
    session.commit()
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    payouts = _family(summary, FreshnessFamilyId.T_INVEST_PAYOUTS)
    statements = _family(summary, FreshnessFamilyId.ALFA_STATEMENT_PAYOUTS)
    assert payouts.status is FreshnessStatus.NOT_APPLICABLE
    assert statements.status is FreshnessStatus.NOT_APPLICABLE
    assert payouts.items[0].source_date == date(2026, 6, 15)
    assert payouts.items[0].fetched_at == FETCHED_AT
    assert payouts.items[0].import_apply_time == APPLIED_AT
    assert statements.items[0].source_date == date(2026, 5, 1)
    assert statements.items[0].import_apply_time == APPLIED_AT
    assert FreshnessReasonCode.PAYOUT_NOT_FRESHNESS_CLASSIFIED in _codes(summary)
    assert FreshnessReasonCode.STATEMENT_NOT_FRESHNESS_CLASSIFIED in _codes(summary)
    assert FreshnessReasonCode.MULTIPLE_PROVIDERS in _codes(summary)
    assert set(summary.providers) == {"alfa_depository_income_report", "t_invest"}
    assert "alfa_pro" not in summary.providers


def test_cash_without_edit_timestamp_is_unavailable_clock_not_stale(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month, _account, deposit_account, _stock, _fund = _seed_month(session)
    create_cash_balance(session, reporting_month_id=month.id, name="Наличные", amount="500.00")
    deposit = create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=deposit_account.id,
        name="Вклад 1",
        deposit_type=DepositType.DEPOSIT,
        balance="1000.00",
        annual_rate="10.00",
    )
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type=IncomeType.OTHER,
        name="Прочее",
        gross_amount="10.00",
        tax_amount="0.00",
        net_amount="10.00",
    )
    create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Еда",
        amount="5.00",
        expense_type=ExpenseType.OTHER,
    )
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    family = _family(summary, FreshnessFamilyId.DEPOSIT_CASH_SNAPSHOTS)
    assert family.status is FreshnessStatus.NOT_APPLICABLE
    cash_item = next(item for item in family.items if item.item_kind == "cash")
    deposit_item = next(item for item in family.items if item.item_kind == "deposit")
    assert cash_item.source_timestamp_kind is SourceTimestampKind.UNAVAILABLE
    assert cash_item.local_edit_time is None
    assert deposit_item.local_edit_time is not None
    assert deposit_item.local_edit_time.replace(tzinfo=None) == deposit.updated_at.replace(
        tzinfo=None
    )
    assert family.coverage.stale_count == 0
    manual = _family(summary, FreshnessFamilyId.MANUAL_MONTH_DATA)
    assert manual.status is FreshnessStatus.NOT_APPLICABLE
    assert FreshnessReasonCode.QUOTE_STALE not in _codes(summary)


def test_closed_month_quote_target_is_snapshot_date_not_today(tmp_path: Path) -> None:
    session, _database = session_for(tmp_path)
    month = create_reporting_month(session, year=2026, month=6, snapshot_date=date(2026, 6, 30))
    account = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    stock = create_instrument(session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 6, 29),
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 6, 29))
    summary = build_freshness_provenance_summary(session, month.id, today=TODAY)
    assert summary.quote_valuation_target_date == date(2026, 6, 30)
    quotes = _family(summary, FreshnessFamilyId.MARKET_QUOTES)
    assert quotes.status is FreshnessStatus.CURRENT
    assert quotes.items[0].freshness_status is FreshnessStatus.CURRENT


def test_api_returns_summary_and_404(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    month, account, _deposit_account, stock, _fund = _seed_month(session)
    snapshot = _t_invest_snapshot(
        session,
        month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        price_date=date(2026, 8, 10),
    )
    _add_quote_provenance(session, snapshot, price_date=date(2026, 8, 10))
    application = create_app(database)
    application.state.quote_preview_clock = lambda: TODAY
    application.state.freshness_generated_at = lambda: GENERATED_AT
    client = TestClient(application)
    missing = client.get("/api/months/999/freshness-provenance")
    assert missing.status_code == 404
    response = client.get(f"/api/months/{month.id}/freshness-provenance")
    assert response.status_code == 200
    body = response.json()
    assert "freshness_score" not in body
    assert "freshness_pct" not in body
    assert body["reporting_month"]["snapshot_date"] == "2026-08-31"
    assert body["evaluated_on"] == "2026-08-27"
    assert body["quote_valuation_target_date"] == "2026-08-27"
    families = {family["family_id"]: family for family in body["families"]}
    assert set(families) == {
        "market_quotes",
        "t_invest_payouts",
        "alfa_pro_positions",
        "alfa_statement_payouts",
        "manual_month_data",
        "deposit_cash_snapshots",
    }
    assert families["market_quotes"]["status"] == "stale"
    quote_item = families["market_quotes"]["items"][0]
    assert quote_item["source_date"] == "2026-08-10"
    assert quote_item["import_apply_time"].startswith("2026-08-21")
    assert families["alfa_pro_positions"]["status"] == "unknown"
    assert families["alfa_pro_positions"]["providers"] == []
    assert "alfa_pro" not in body["providers"]
    assert "multiple_providers" not in {reason["code"] for reason in body["reasons"]}
    assert any(reason["code"] == "quote_stale" for reason in body["reasons"])
    assert any(
        reason["code"] == "alfa_pro_observation_not_persisted"
        for reason in families["alfa_pro_positions"]["reasons"]
    )
    forbidden = {"freshness_score", "freshness_pct", "overall_freshness", "freshness_percent"}

    def _walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for child in value:
                _walk(child)

    _walk(body)
