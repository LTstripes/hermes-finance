"""Integration tests for the ORM monthly-summary service (C10).

Covers the wiring of every Phase-C calculator into the unified
:class:`MonthlySummaryResult` against a real SQLite database:
- empty month assembly (None deltas, delta warning, ``calculation_version``);
- two-month delta matrix with hand-computed kopecks;
- ``forecast_version`` passthrough into forecast and coverage;
- warnings aggregation order (normalized bonus before delta warning);
- IIS wiring (one IIS account + received benefit, non-IIS adds nothing);
- deltas react only to liquid capital and passive income series.

All amounts are exact integer kopecks via :class:`RubleAmount`; every
fixture value is synthetic (2031/2032).
"""

from datetime import date
from pathlib import Path

import pytest
from _month_close_helpers import close_fixture_month
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DepositType,
    ExpectedCashFlowType,
    IncomeType,
    InstrumentType,
    RubleAmount,
    TaxBenefitStatus,
)
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash_balance import cash_balance_for_month
from hermes_finance.services.coverage_goals import coverage_and_goals
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.iis import create_iis_profile, create_tax_benefit
from hermes_finance.services.income_plan_summary import income_plan_summary
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.monthly_summary import monthly_summary
from hermes_finance.services.reporting_months import create_reporting_month

DELTA_WARNING = "Нет предыдущего месяца для расчёта дельты"
NORM_BONUS_WARNING = "Нет закрытых месяцев для оценки нормализованной премии"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "monthly_summary.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, year: int, month: int) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 10)
    )
    return reporting_month.id


def add_deposit(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    balance: str,
    actual_interest_received: str,
) -> None:
    create_deposit_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        name="Synthetic Deposit 1",
        deposit_type=DepositType.DEPOSIT,
        balance=balance,
        annual_rate="10.00",
        actual_interest_received=actual_interest_received,
    )


def add_salary(session: Session, *, month_id: int, net_amount: str) -> None:
    create_income_entry(
        session,
        reporting_month_id=month_id,
        income_type=IncomeType.SALARY,
        name="Synthetic Salary",
        gross_amount=net_amount,
        tax_amount="0.00",
        net_amount=net_amount,
    )


# --- empty month (single month, no data at all) ---


def test_empty_month_assembles(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        summary = monthly_summary(session, month_id)

        assert summary.year == 2031
        assert summary.month == 1
        assert summary.calculation_version == "v3"
        assert summary.iis == ()
        assert summary.liquid_capital.liquid_capital_net == RubleAmount(0)
        assert summary.passive_income_actual == RubleAmount(0)
        # no previous month -> deltas are None
        assert summary.liquid_capital_delta is None
        assert summary.passive_income_delta is None
        # delta warning present and appended last
        assert DELTA_WARNING in summary.warnings
        assert summary.warnings[-1] == DELTA_WARNING
    finally:
        session.close()
        database.engine.dispose()


# --- two months with different liquid capital and passive income ---


def test_two_months_deltas_hand_computed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        jan_id = build_month(session, 2031, 1)
        feb_id = build_month(session, 2031, 2)
        deposit_account = create_account(
            session, name="Synthetic Deposit Account", account_type=AccountType.DEPOSIT
        )
        # Jan: 100000.00 balance / 3000.00 interest; Feb: 150000.00 / 4500.00
        add_deposit(
            session,
            month_id=jan_id,
            account_id=deposit_account.id,
            balance="100000.00",
            actual_interest_received="3000.00",
        )
        add_deposit(
            session,
            month_id=feb_id,
            account_id=deposit_account.id,
            balance="150000.00",
            actual_interest_received="4500.00",
        )

        jan = monthly_summary(session, jan_id)
        feb = monthly_summary(session, feb_id)

        # Jan has no previous month: deltas are None.
        assert jan.liquid_capital_delta is None
        assert jan.passive_income_delta is None
        assert DELTA_WARNING in jan.warnings

        # Exact kopecks: 100000.00 RUB = 10_000_000; 150000.00 RUB = 15_000_000.
        assert jan.liquid_capital.liquid_capital_net == RubleAmount(10_000_000)
        assert feb.liquid_capital.liquid_capital_net == RubleAmount(15_000_000)
        assert feb.liquid_capital_delta == RubleAmount(5_000_000)  # 50000.00 RUB

        # Passive income: 3000.00 RUB = 300_000; 4500.00 RUB = 450_000 kopecks.
        assert jan.passive_income_actual == RubleAmount(300_000)
        assert feb.passive_income_actual == RubleAmount(450_000)
        assert feb.passive_income_delta == RubleAmount(150_000)  # 1500.00 RUB

        # Feb has a previous month: no delta warning.
        assert DELTA_WARNING not in feb.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- forecast_version passthrough ---


def test_forecast_version_passthrough(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        # A v2-only expected coupon: 1000.00 gross, 130.00 tax, 870.00 net.
        create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2031, 11, 1),
            gross_amount="1000.00",
            expected_tax_amount="130.00",
            expected_net_amount="870.00",
            source="synthetic calendar",
            source_as_of_date=date(2031, 1, 10),
            forecast_version="v2",
        )

        # v2: the flow is seen by the forecast and coverage.
        v2_summary = monthly_summary(session, month_id, forecast_version="v2")
        assert v2_summary.forecast.annual_total == RubleAmount(87_000)  # 870.00 RUB
        assert v2_summary.forecast.monthly_total == RubleAmount(7_250)  # 87000/12
        assert v2_summary.coverage.forecast_monthly == RubleAmount(7_250)

        # Default v1: the v2 flow is excluded from the forecast.
        v1_summary = monthly_summary(session, month_id)
        assert v1_summary.forecast.annual_total == RubleAmount(0)
        assert v1_summary.calculation_version == "v3"
    finally:
        session.close()
        database.engine.dispose()


def test_income_plan_summary_reuses_canonical_planning_services(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 6)
        close_fixture_month(session, month_id)

        result = income_plan_summary(session, month_id, forecast_version="v2")

        assert result.month.id == month_id
        assert result.forecast_version == "v2"
        assert result.forecast == forecast_passive_income(session, month_id, "v2")
        assert result.coverage == coverage_and_goals(session, month_id, "v2")
        assert result.cash_balance == cash_balance_for_month(session, month_id)
        assert result.warnings == result.coverage.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- warnings aggregation: no closed months + no previous month ---


def test_warnings_aggregation_no_closed_months_and_no_previous(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2032, 1)
        summary = monthly_summary(session, month_id)

        assert NORM_BONUS_WARNING in summary.warnings
        assert DELTA_WARNING in summary.warnings
        # Fixed order: normalized-bonus warning comes before the delta warning,
        # and the delta warning is the final element.
        assert summary.warnings.index(NORM_BONUS_WARNING) < summary.warnings.index(DELTA_WARNING)
        assert summary.warnings[-1] == DELTA_WARNING
        # Forecast warnings are also aggregated.
        assert "Нет закрытых месяцев для оценки дивидендного компонента" in summary.warnings
        assert "Нет ожидаемых выплат в календаре прогноза" in summary.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- IIS wiring ---


def test_iis_wiring_received_benefit_and_non_iis_ignored(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 3)
        iis_account = create_account(
            session, name="Synthetic IIS Account", account_type=AccountType.IIS
        )
        create_iis_profile(
            session,
            account_id=iis_account.id,
            iis_type="A",
            opened_at=date(2031, 1, 1),
        )
        create_tax_benefit(
            session,
            account_id=iis_account.id,
            tax_year=2031,
            benefit_type="A",
            status=TaxBenefitStatus.RECEIVED,
            amount="52000.00",
        )

        summary = monthly_summary(session, month_id)
        assert len(summary.iis) == 1
        assert summary.iis[0].portfolio_result_without_tax_benefit == RubleAmount(0)
        # 52000.00 RUB = 5_200_000 kopecks.
        assert summary.iis[0].portfolio_result_with_tax_benefit == RubleAmount(5_200_000)
        assert summary.iis[0].breakdown.received_tax_benefits == RubleAmount(5_200_000)

        # A second, non-IIS account must not add anything to the IIS tuple.
        create_account(session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE)
        summary_after = monthly_summary(session, month_id)
        assert len(summary_after.iis) == 1
    finally:
        session.close()
        database.engine.dispose()


# --- deltas react only to liquid capital and passive income ---


def test_deltas_only_liquid_capital_and_passive_income(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        jan_id = build_month(session, 2031, 1)
        feb_id = build_month(session, 2031, 2)
        deposit_account = create_account(
            session, name="Synthetic Deposit Account", account_type=AccountType.DEPOSIT
        )
        # Identical capital and passive income in both months.
        add_deposit(
            session,
            month_id=jan_id,
            account_id=deposit_account.id,
            balance="100000.00",
            actual_interest_received="3000.00",
        )
        add_deposit(
            session,
            month_id=feb_id,
            account_id=deposit_account.id,
            balance="100000.00",
            actual_interest_received="3000.00",
        )
        # Only the salary entry differs between the months.
        add_salary(session, month_id=jan_id, net_amount="100000.00")
        add_salary(session, month_id=feb_id, net_amount="150000.00")

        jan = monthly_summary(session, jan_id)
        close_fixture_month(session, jan_id)
        feb = monthly_summary(session, feb_id)

        # Salary is neither liquid capital nor passive income, so a salary-only
        # change must leave both deltas at exactly zero kopecks (not None).
        assert jan.liquid_capital.liquid_capital_net == RubleAmount(10_000_000)
        assert feb.liquid_capital.liquid_capital_net == RubleAmount(10_000_000)
        assert jan.passive_income_actual == RubleAmount(300_000)
        assert feb.passive_income_actual == RubleAmount(300_000)
        assert feb.liquid_capital_delta is not None
        assert feb.passive_income_delta is not None
        assert feb.liquid_capital_delta == RubleAmount(0)
        assert feb.passive_income_delta == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "external,end,interest,residual",
    [
        (None, "1000.01", "0.00", "0.00"),
        ("-200.02", "800.49", "0.50", "0.00"),
        ("200.02", "1200.60", "0.50", "0.07"),
    ],
)
def test_monthly_capital_bridge_reconciles_synthetic_activity(
    tmp_path,
    external,
    end,
    interest,
    residual,
):
    from hermes_finance.persistence import AccountPerformanceScopeMembership
    from hermes_finance.services.external_flows import create_external_flow

    session, database = session_for(tmp_path)
    try:
        jan = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
        feb = create_reporting_month(session, year=2031, month=2, snapshot_date=date(2031, 2, 28))
        account = create_account(session, name="Synthetic bridge deposit", account_type="deposit")
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id,
                effective_from=date(2031, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
        add_deposit(
            session,
            month_id=jan.id,
            account_id=account.id,
            balance="1000.01",
            actual_interest_received="0.00",
        )
        add_deposit(
            session,
            month_id=feb.id,
            account_id=account.id,
            balance=end,
            actual_interest_received=interest,
        )
        if external is not None:
            direction = "withdrawal" if external.startswith("-") else "contribution"
            create_external_flow(
                session,
                reporting_month_id=feb.id,
                account_id=account.id,
                event_date=date(2031, 2, 12),
                boundary_amount=external.lstrip("-"),
                direction=direction,
                kind="external_" + direction,
                scope_membership="stable_in_scope",
                source="synthetic",
            )
        result = monthly_summary(session, feb.id).capital_change
        assert result is not None and result.breakdown is not None
        bridge = result.breakdown
        assert bridge.start.to_api() == "1000.01"
        assert bridge.external_net.to_api() == (external or "0.00")
        assert bridge.investment_result.to_api() == interest
        assert bridge.other_changes.to_api() == "0.00"
        assert bridge.unexplained.to_api() == residual
        assert (
            sum(
                value.kopecks
                for value in (
                    bridge.start,
                    bridge.external_net,
                    bridge.investment_result,
                    bridge.other_changes,
                    bridge.unexplained,
                )
            )
            == bridge.end.kopecks
        )
    finally:
        session.close()
        database.engine.dispose()


def test_capital_bridge_does_not_infer_missing_calendar_month(tmp_path):
    session, database = session_for(tmp_path)
    try:
        create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
        march = create_reporting_month(session, year=2031, month=3, snapshot_date=date(2031, 3, 31))
        result = monthly_summary(session, march.id).capital_change
        assert result.breakdown is None
        assert result.flow_breakdown is None
        assert result.context_hints == ()
        assert "capital_calendar_gap" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


@pytest.fixture
def capital_flow_months(tmp_path):
    session, database = session_for(tmp_path)
    try:
        jan = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
        feb = create_reporting_month(session, year=2031, month=2, snapshot_date=date(2031, 2, 28))
        yield session, jan, feb
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("record_expense", [True, False])
def test_capital_flow_card_purchase_and_saving_allocation(capital_flow_months, record_expense):
    from hermes_finance.services.debts import create_debt
    from hermes_finance.services.expenses import create_expense_entry, create_saving_allocation

    session, jan, feb = capital_flow_months
    account = create_account(session, name="Synthetic flow deposit", account_type="deposit")
    for month, balance in ((jan, "1000.00"), (feb, "1300.00")):
        add_deposit(
            session,
            month_id=month.id,
            account_id=account.id,
            balance=balance,
            actual_interest_received="0.00",
        )
    for month, debt in ((jan, "0.00"), (feb, "200.00")):
        create_debt(
            session,
            reporting_month_id=month.id,
            debt_type="credit_card",
            name="Synthetic card",
            current_balance=debt,
        )
    create_income_entry(
        session,
        reporting_month_id=feb.id,
        income_type="side_income",
        name="Synthetic income",
        gross_amount="300.00",
        net_amount="300.00",
        tax_amount="0.00",
    )
    create_saving_allocation(
        session,
        reporting_month_id=feb.id,
        destination="Synthetic reserve",
        amount="80.00",
    )
    if record_expense:
        create_expense_entry(
            session,
            reporting_month_id=feb.id,
            category="Synthetic purchase",
            amount="200.00",
            expense_type="other",
        )
    result = monthly_summary(session, feb.id).capital_change
    flow = result.flow_breakdown
    assert flow is not None
    assert flow.monthly_flow.to_api() == ("100.00" if record_expense else "300.00")
    assert flow.unexplained.to_api() == ("0.00" if record_expense else "-200.00")
    assert flow.end.kopecks - flow.start.kopecks == 10_000
    assert flow.investment_market_change.amount == RubleAmount(0)
    assert flow.physical_gold_revaluation.amount == RubleAmount(0)
    if record_expense:
        assert result.context_hints == ()
    else:
        (hint,) = result.context_hints
        assert hint.reason_code == "card_debt_growth_exceeds_recorded_expenses"
        assert hint.card_debt_growth.to_api() == "200.00"
        assert hint.recorded_expenses.to_api() == "0.00"


def test_capital_flow_linked_pair_repayment_is_internal(capital_flow_months):
    from hermes_finance.services.debts import create_debt, link_debt_to_account

    session, jan, feb = capital_flow_months
    account = create_account(session, name="Synthetic reserve", account_type="deposit")
    for month, balance, debt in ((jan, "1000.00", "200.00"), (feb, "800.00", "0.00")):
        add_deposit(
            session,
            month_id=month.id,
            account_id=account.id,
            balance=balance,
            actual_interest_received="0.00",
        )
        debt_row = create_debt(
            session,
            reporting_month_id=month.id,
            debt_type="credit_card",
            name="Synthetic linked card",
            current_balance=debt,
        )
        link_debt_to_account(session, debt_row.id, account.id)
    summary = monthly_summary(session, feb.id)
    (pair,) = summary.liquid_capital.linked_pairs
    assert pair.net_contribution.to_api() == "800.00"
    flow = summary.capital_change.flow_breakdown
    assert flow.start == flow.end == RubleAmount(80_000)
    assert flow.monthly_flow == flow.unexplained == RubleAmount(0)
    assert summary.capital_change.context_hints == ()


@pytest.mark.parametrize("case", ["same", "changed", "missing", "future", "partial"])
def test_capital_flow_gold_revaluation_preserves_unknown(capital_flow_months, case):
    from hermes_finance.services.positions import create_position_snapshot

    session, jan, feb = capital_flow_months
    account = create_account(session, name="Synthetic physical metal", account_type="other")
    instrument = create_instrument(session, name="Synthetic gold", instrument_type="gold")
    for month, price, quantity in (
        (jan, "100.00", "2"),
        (feb, "90.00", "3" if case == "changed" else "2"),
    ):
        if case == "missing" and month.id == jan.id:
            # Preserve endpoint capital evidence without inventing a gold valuation.
            from hermes_finance.services.cash import create_cash_balance

            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic cash",
                amount="0.00",
            )
            continue
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=quantity,
            average_cost_per_unit="100.00",
            market_price_per_unit=price,
            price_date=date(2031, 3, 1)
            if case == "future" and month.id == feb.id
            else month.snapshot_date,
        )
    if case == "partial":
        second = create_instrument(session, name="Synthetic unknown gold", instrument_type="gold")
        create_position_snapshot(
            session,
            reporting_month_id=feb.id,
            account_id=account.id,
            instrument_id=second.id,
            quantity="1",
            average_cost_per_unit="50.00",
            market_price_per_unit="50.00",
            price_date=feb.snapshot_date,
        )
    flow = monthly_summary(session, feb.id).capital_change.flow_breakdown
    gold = flow.physical_gold_revaluation
    if case == "same":
        assert gold.amount.to_api() == "-20.00"
        assert flow.unexplained == RubleAmount(0)
    else:
        assert gold.amount is None
        assert gold.reason_codes
        assert any(item.amount is None for item in gold.items)
        assert gold.known_subtotal.to_api() == ("-20.00" if case == "partial" else "0.00")
        assert (
            flow.unexplained.to_api()
            == {
                "changed": "70.00",
                "missing": "180.00",
                "future": "-20.00",
                "partial": "50.00",
            }[case]
        )
    assert (
        flow.start.kopecks
        + flow.monthly_flow.kopecks
        + gold.known_subtotal.kopecks
        + flow.unexplained.kopecks
        == flow.end.kopecks
    )


@pytest.mark.parametrize(
    "case",
    [
        "known",
        "missing",
        "assumed",
        "unknown_flow",
        "mismatch",
        "partial",
        "both",
        "sections",
        "missing_row",
        "estimate",
        "opening_mismatch",
        "both_endpoints",
        "sections_and_mismatch",
    ],
)
def test_capital_flow_investments_exclude_recorded_payouts(capital_flow_months, monkeypatch, case):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from hermes_finance.services import monthly_capital_change as service
    from hermes_finance.services.cash import create_cash_balance
    from hermes_finance.services.investment_cash_flows import create_investment_cash_flow

    session, jan, feb = capital_flow_months
    broker = create_account(session, name="Synthetic broker", account_type="brokerage")
    deposit = create_account(session, name="Synthetic interest", account_type="deposit")
    # Broker: 1000 + funding 100 + coupon 10 + dividend 5 + market change 20.
    # Deposit: 500 - internal funding 100 + interest 3.
    for month, cash, balance, interest in (
        (jan, "1000.00", "500.00", "0.00"),
        (feb, "1135.00", "403.00", "3.00"),
    ):
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=broker.id,
            name="Synthetic account value",
            amount=cash,
        )
        add_deposit(
            session,
            month_id=month.id,
            account_id=deposit.id,
            balance=balance,
            actual_interest_received=interest,
        )
    for kind, amount in (("coupon", "10.00"), ("dividend", "5.00")):
        create_investment_cash_flow(
            session,
            reporting_month_id=feb.id,
            account_id=broker.id,
            flow_type=kind,
            net_amount=amount,
            gross_amount=amount,
            event_date=date(2031, 2, 15),
            source="synthetic",
        )
    row = SimpleNamespace(
        opening_kopecks=None
        if case == "missing"
        else 100_001
        if case in {"opening_mismatch", "both_endpoints"}
        else 100_000,
        closing_kopecks=113_501
        if case in {"mismatch", "both", "both_endpoints", "sections_and_mismatch"}
        else 113_500,
        contributions_kopecks=None
        if case in {"unknown_flow", "both", "sections", "sections_and_mismatch"}
        else 10_000,
        withdrawals_kopecks=0,
        growth_kopecks=None if case == "missing" else 3500,
        assumptions_used=case == "assumed",
        approximate=case == "estimate",
        reason_codes=("unknown_flow", "4_Transfers_unsupported")
        if case in {"sections", "sections_and_mismatch"}
        else ("unknown_flow",)
        if case in {"unknown_flow", "both"}
        else ("missing_endpoint",)
        if case == "missing"
        else (),
    )
    monkeypatch.setattr(service, "_source_scopes", lambda session: {"synthetic": "synthetic"})
    monkeypatch.setattr(
        service,
        "account_link",
        lambda *args: {"status": "linked", "financial_account_id": broker.id},
    )
    monkeypatch.setattr(service, "source_read_snapshot", lambda session: nullcontext())
    monkeypatch.setattr(
        service,
        "read_monthly_result",
        lambda *args, **kwargs: None if case == "missing_row" else row,
    )
    if case == "partial":
        other = create_account(session, name="Synthetic unlinked IIS", account_type="iis")
        for month, cash in ((jan, "100.00"), (feb, "107.00")):
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=other.id,
                name="Synthetic unlinked value",
                amount=cash,
            )
    change = monthly_summary(session, feb.id).capital_change
    flow = change.flow_breakdown
    assert flow.monthly_flow.to_api() == "18.00"
    investments = flow.investment_market_change
    if case in {"known", "estimate"}:
        assert investments.amount.to_api() == "20.00"
        assert flow.unexplained == RubleAmount(0)
        assert investments.items[0].unavailable_hint is None
    elif case == "partial":
        assert investments.amount is None
        assert investments.known_subtotal.to_api() == "20.00"
        assert flow.unexplained.to_api() == "7.00"
    else:
        assert investments.amount is None
        assert investments.items[0].amount is None
        assert investments.reason_codes
        assert flow.unexplained.to_api() == "20.00"
        assert investments.items[0].unavailable_hint

    from hermes_finance.api.analytics import capital_change_to_out

    item = investments.items[0]
    serialized = capital_change_to_out(change).model_dump(mode="json")["flow_breakdown"][
        "investment_market_change"
    ]["items"][0]
    assert serialized["source_reason_codes"] == list(item.source_reason_codes)
    assert serialized["unavailable_hint"] == item.unavailable_hint
    assert item.source_reason_codes == (() if case == "missing_row" else row.reason_codes)
    if case in {"mismatch", "both"}:
        assert item.reason_codes == ("capital_investment_endpoints_unproven",)
        assert "28.02.2031" in item.unavailable_hint
        assert "31.01.2031" not in item.unavailable_hint
    if case == "both":
        assert "денежные движения" in item.unavailable_hint
    if case in {"opening_mismatch", "both_endpoints"}:
        assert "31.01.2031" in item.unavailable_hint
        assert ("28.02.2031" in item.unavailable_hint) == (case == "both_endpoints")
    if case in {"sections", "sections_and_mismatch"}:
        assert "одной классификации денег недостаточно" in item.unavailable_hint
    if case == "sections_and_mismatch":
        assert "28.02.2031" in item.unavailable_hint
        assert item.reason_codes == ("capital_investment_endpoints_unproven",)
    if case == "assumed":
        assert "предположения" in item.unavailable_hint
    if case == "missing":
        assert "границы месяца" in item.unavailable_hint
        assert "денежные движения" not in item.unavailable_hint
    if case == "partial":
        assert investments.items[1].unavailable_hint


@pytest.mark.parametrize("case", ["linked", "unlinked", "mismatch", "excluded"])
def test_capital_bridge_reuses_exact_account_returns_without_payout_double_count(tmp_path, case):
    from test_source_monthly_returns_service import save_month
    from test_statement_import_mybroker import ACCOUNT

    from hermes_finance.services.broker_identity_mappings import confirm_mapping
    from hermes_finance.services.cash import create_cash_balance
    from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
    from hermes_finance.services.liquid_capital import liquid_capital_for_month
    from hermes_finance.services.monthly_capital_change import monthly_capital_change
    from hermes_finance.statement_import.mybroker import PROVIDER

    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session,
            name="Synthetic source return account",
            account_type="brokerage",
            include_in_capital=case != "excluded",
        )
        if case != "unlinked":
            for identity in (ACCOUNT, "1234567"):
                confirm_mapping(
                    session,
                    provider=PROVIDER,
                    subject_kind="account",
                    provider_identity=identity,
                    hermes_target_id=account.id,
                )
        save_month(database)
        march = create_reporting_month(
            session,
            year=2030,
            month=3,
            snapshot_date=date(2030, 3, 31),
        )
        april = create_reporting_month(
            session,
            year=2030,
            month=4,
            snapshot_date=date(2030, 4, 30),
        )
        for month, amount in ((march, "10000.00"), (april, "11211.00")):
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic saved account value",
                amount=amount,
                include_in_capital=case != "excluded",
            )
        # This separate accepted payment is already inside account economics;
        # it must never be added on top of the source-account period P&L.
        create_investment_cash_flow(
            session,
            reporting_month_id=april.id,
            account_id=account.id,
            flow_type="coupon",
            net_amount="100.00",
            gross_amount="100.00",
            event_date=date(2030, 4, 15),
            source="synthetic",
        )
        if case == "mismatch":
            from hermes_finance.persistence import CashBalance

            cash = session.scalar(
                select(CashBalance).where(
                    CashBalance.reporting_month_id == april.id,
                )
            )
            cash.amount_kopecks += 1
            session.commit()
        result = monthly_capital_change(
            session,
            current=april,
            previous=march,
            liquid=liquid_capital_for_month(session, april.id),
            previous_liquid=liquid_capital_for_month(session, march.id),
        )
        if case == "excluded":
            assert result.breakdown is not None
            assert result.breakdown.investment_result == RubleAmount(0)
            assert result.breakdown.end == RubleAmount(0)
            return
        assert result.breakdown is not None
        assert result.breakdown.investment_result.to_api() == (
            "211.00" if case == "linked" else "0.00"
        )
        assert result.breakdown.unexplained.to_api() == (
            "1000.00" if case == "linked" else "1211.01" if case == "mismatch" else "1211.00"
        )
        if case == "linked":
            assert "capital_investment_source_estimate" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "scope_case", ["matching", "missing_roster", "unassigned_cash", "excluded"]
)
def test_capital_bridge_does_not_promote_account_or_unknown_scope_funding(tmp_path, scope_case):
    from hermes_finance.persistence import AccountPerformanceScopeMembership
    from hermes_finance.services.cash import create_cash_balance
    from hermes_finance.services.external_flows import create_external_flow

    session, database = session_for(tmp_path)
    try:
        jan = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
        feb = create_reporting_month(session, year=2031, month=2, snapshot_date=date(2031, 2, 28))
        account = create_account(
            session,
            name="Synthetic scope account",
            account_type="deposit",
            include_in_capital=scope_case != "excluded",
        )
        add_deposit(
            session,
            month_id=jan.id,
            account_id=account.id,
            balance="1000.00",
            actual_interest_received="0.00",
        )
        add_deposit(
            session,
            month_id=feb.id,
            account_id=account.id,
            balance="1100.00",
            actual_interest_received="0.00",
        )
        if scope_case == "unassigned_cash":
            for month in (jan, feb):
                create_cash_balance(
                    session,
                    reporting_month_id=month.id,
                    name="Synthetic unassigned zero",
                    amount="0.00",
                )
        if scope_case != "missing_roster":
            session.add(
                AccountPerformanceScopeMembership(
                    account_id=account.id,
                    effective_from=date(2031, 1, 1),
                    include_in_returns=scope_case != "excluded",
                )
            )
            session.commit()
        create_external_flow(
            session,
            reporting_month_id=feb.id,
            account_id=account.id,
            event_date=date(2031, 2, 12),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
            source="synthetic",
        )
        result = monthly_summary(session, feb.id).capital_change
        assert result.breakdown is not None
        assert result.breakdown.external_net.to_api() == (
            "100.00" if scope_case == "matching" else "0.00"
        )
        if scope_case in {"missing_roster", "unassigned_cash"}:
            assert "capital_external_scope_unproven" in result.reason_codes
            assert result.breakdown.unexplained.to_api() == "100.00"
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("failure", ["maintenance", "snapshot_mutation", "snapshot_cleanup", "sql"])
def test_optional_capital_explanation_does_not_hide_database_guards(tmp_path, monkeypatch, failure):
    from sqlalchemy.exc import SQLAlchemyError

    from hermes_finance.database import (
        DatabaseMaintenanceError,
        ReadSnapshotCleanupError,
        ReadSnapshotMutationError,
    )
    from hermes_finance.services import monthly_capital_change as capital_change_service

    errors = {
        "maintenance": DatabaseMaintenanceError,
        "snapshot_mutation": ReadSnapshotMutationError,
        "snapshot_cleanup": ReadSnapshotCleanupError,
        "sql": SQLAlchemyError,
    }
    error_type = errors[failure]
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)

        def refused_calculation(*args, **kwargs):
            raise error_type("synthetic database boundary failure")

        monkeypatch.setattr(capital_change_service, "_monthly_capital_change", refused_calculation)
        with pytest.raises(error_type, match="synthetic database boundary failure"):
            monthly_summary(session, month_id)
    finally:
        session.close()
        database.engine.dispose()
