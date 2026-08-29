"""Synthetic R08-01C performance-availability regression coverage."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExternalFlowClassification,
    PerformanceAvailabilityStatus,
    PerformanceScope,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    Base,
    CashBalance,
    Instrument,
    InvestmentCashFlow,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import (
    create_external_flow,
    create_external_transfer_link,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

START = date(2030, 1, 31)
END = date(2030, 2, 28)


def _environment(
    tmp_path: Path,
    *,
    with_membership_history: bool = True,
) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-01c.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    account = create_account(
        session,
        name="Synthetic Performance Account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic Performance Bond",
        instrument_type="bond",
    )

    for month in (january, february):
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit="1000.00",
            market_price_per_unit="1100.00",
            price_date=month.snapshot_date,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic Performance Deposit",
            deposit_type="deposit",
            balance="2000.00",
            annual_rate="10.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic Performance Cash",
            amount="300.00",
        )

    if with_membership_history:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
    return session, database, january.id, february.id, account.id


def _close_two_months(session: Session, january_id: int, february_id: int) -> None:
    close_reporting_month(session, january_id)
    close_reporting_month(session, february_id)


def test_available_interval_exposes_exact_boundaries_and_both_prerequisites(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        _close_two_months(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=account_id,
        )

        assert result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert result.reason_codes == ()
        assert result.xirr.is_available
        assert result.twrr.is_available
        assert result.opening_valuation.reporting_month_id == january_id
        assert result.closing_valuation.reporting_month_id == february_id
        assert result.opening_valuation.point is not None
        assert result.closing_valuation.point is not None
        assert result.opening_valuation.point.total_value is not None
        assert result.opening_valuation.point.total_value.kopecks == 340_000
        assert result.closing_valuation.point.total_value is not None
        assert result.external_flows.is_complete
        assert result.external_flows.flows == ()
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_scope_uses_historical_membership_not_current_account_flag(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        _close_two_months(session, january_id, february_id)
        before = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope="portfolio"
        )
        current_account = session.get(Account, account_id)
        assert current_account is not None
        current_account.include_in_returns = False
        session.commit()
        after = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope="portfolio"
        )

        assert before.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert after.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert after.opening_valuation.point is not None
        assert after.opening_valuation.point.total_value is not None
        assert after.opening_valuation.point.total_value.kopecks == 340_000
    finally:
        session.close()
        database.engine.dispose()


def test_mid_interval_external_flow_is_xirr_ready_but_twrr_boundary_missing(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=date(2030, 2, 15),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _close_two_months(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_missing",)
        assert result.external_flows.status == "complete"
        assert result.external_flows.flows[0].classification is (
            ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )
        assert result.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
    finally:
        session.close()
        database.engine.dispose()


def test_same_day_flow_is_xirr_ready_but_twrr_order_unknown(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        create_external_flow(
            session,
            reporting_month_id=january_id,
            account_id=account_id,
            event_date=START,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _close_two_months(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.opening_valuation.is_available
        assert result.opening_valuation.point is not None
        assert result.opening_valuation.point.coverage.reason_codes == (
            "not_computable_valuation_boundary_order_unknown",
        )
        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_order_unknown",)
        assert result.reason_codes == ("not_computable_valuation_boundary_order_unknown",)
    finally:
        session.close()
        database.engine.dispose()


def test_resolved_transfer_is_internal_for_portfolio_and_external_for_account(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        destination = create_account(
            session,
            name="Synthetic Transfer Destination",
            account_type=AccountType.BROKERAGE,
        )
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        for month_id, snapshot_date in ((january_id, START), (february_id, END)):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=destination.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="500.00",
                market_price_per_unit="550.00",
                price_date=snapshot_date,
            )
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=destination.id,
                name="Synthetic Transfer Deposit",
                deposit_type="deposit",
                balance="500.00",
                annual_rate="10.00",
            )
            create_cash_balance(
                session,
                reporting_month_id=month_id,
                account_id=destination.id,
                name="Synthetic Transfer Cash",
                amount="50.00",
            )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=destination.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
        link = create_external_transfer_link(session, transfer_key="synthetic-resolved")
        source_flow = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=date(2030, 2, 15),
            boundary_amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        destination_flow = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=destination.id,
            event_date=date(2030, 2, 15),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        _close_two_months(session, january_id, february_id)

        account_result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        portfolio_result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )

        assert account_result.external_flows.flows[0].id == source_flow.id
        assert account_result.external_flows.flows[0].transfer_status.value == "resolved"
        assert account_result.external_flows.flows[0].classification is (
            ExternalFlowClassification.EXTERNAL_WITHDRAWAL
        )
        assert "not_computable_transfer_identity_unresolved" not in (
            account_result.xirr.reason_codes
        )
        assert portfolio_result.external_flows.flows[0].id == source_flow.id
        assert portfolio_result.external_flows.flows[1].id == destination_flow.id
        assert all(
            flow.classification is ExternalFlowClassification.INTERNAL_TRANSFER
            for flow in portfolio_result.external_flows.flows
        )
        assert portfolio_result.xirr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_missing_opening_and_closing_snapshot_dates_fail_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        _close_two_months(session, january_id, february_id)
        missing_opening = performance_availability_for_interval(
            session,
            start_date=date(2030, 1, 30),
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        missing_closing = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=date(2030, 3, 31),
            scope="account",
            account_id=account_id,
        )

        assert missing_opening.opening_valuation.point is None
        assert missing_opening.xirr.reason_codes == ("not_computable_opening_valuation_missing",)
        assert missing_closing.closing_valuation.point is None
        assert missing_closing.xirr.reason_codes == ("not_computable_closing_valuation_missing",)
    finally:
        session.close()
        database.engine.dispose()


def test_legacy_deposit_or_withdrawal_blocks_external_flow_completeness(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        session.add(
            InvestmentCashFlow(
                reporting_month_id=february_id,
                account_id=account_id,
                instrument_id=None,
                flow_type="deposit",
                event_date=date(2030, 2, 15),
                gross_amount_kopecks=10_000,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
                net_amount_kopecks=10_000,
                currency="RUB",
                source="synthetic-legacy",
            )
        )
        session.commit()
        _close_two_months(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.xirr.is_available
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
        assert result.external_flows.legacy_unclassified_flow_ids
    finally:
        session.close()
        database.engine.dispose()


def test_scope_membership_history_missing_is_not_replaced_by_current_flag(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(
        tmp_path, with_membership_history=False
    )
    try:
        _close_two_months(session, january_id, february_id)
        account = session.get(Account, account_id)
        assert account is not None
        account.include_in_returns = True
        session.commit()
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.xirr.is_available
        assert "not_computable_scope_membership_history_missing" in result.xirr.reason_codes
        assert result.scope_membership.missing_or_ambiguous_account_ids == (account_id,)
    finally:
        session.close()
        database.engine.dispose()


def test_missing_component_and_unclassified_cash_are_not_zeroed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        cash = session.scalar(
            select(CashBalance).where(
                CashBalance.reporting_month_id == february_id,
                CashBalance.account_id == account_id,
            )
        )
        assert cash is not None
        session.delete(cash)
        session.commit()
        _close_two_months(session, january_id, february_id)
        missing_component = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert "not_computable_scope_coverage_incomplete" in missing_component.xirr.reason_codes
        assert missing_component.closing_valuation.point is not None
        assert missing_component.closing_valuation.point.total_value is None

        session.close()
        database.engine.dispose()
        session, database, january_id, february_id, account_id = _environment(tmp_path / "cash")
        create_cash_balance(
            session,
            reporting_month_id=february_id,
            name="Synthetic Unassigned Cash",
            amount="1.00",
        )
        _close_two_months(session, january_id, february_id)
        unclassified_cash = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert "not_computable_scope_cash_unclassified" in unclassified_cash.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_currency_and_unresolved_transfer_fail_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=date(2030, 2, 15),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
            currency="USD",
        )
        _close_two_months(session, january_id, february_id)
        foreign = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert "not_computable_currency_conversion_incomplete" in foreign.xirr.reason_codes

        session.close()
        database.engine.dispose()
        session, database, january_id, february_id, account_id = _environment(tmp_path / "transfer")
        link = create_external_transfer_link(session, transfer_key="synthetic-unresolved")
        create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=date(2030, 2, 15),
            boundary_amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        _close_two_months(session, january_id, february_id)
        unresolved = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert "not_computable_transfer_identity_unresolved" in unresolved.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_read_only_api_returns_scope_interval_and_no_metric_value(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            closed_session = database.session_factory()
            _close_two_months(closed_session, january_id, february_id)
            closed_session.close()
            response = client.get(
                "/api/performance/availability",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "account",
                    "account_id": account_id,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["availability"] == "available"
            assert body["scope"] == "account"
            assert body["account_id"] == account_id
            assert body["opening_valuation"]["total_value"] == {
                "amount": "3400.00",
                "currency": "RUB",
            }
            assert body["closing_valuation"]["provenance"]
            assert body["external_flows"]["status"] == "complete"
            assert body["xirr"]["availability"] == "available"
            assert body["twrr"]["availability"] == "available"
            assert "return" not in body
            assert "percentage" not in body
    finally:
        database.engine.dispose()


def test_api_rejects_ambiguous_scope_arguments(tmp_path: Path) -> None:
    session, database, _january_id, _february_id, account_id = _environment(tmp_path)
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/availability",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "portfolio",
                    "account_id": account_id,
                },
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "unprocessable"
    finally:
        database.engine.dispose()
