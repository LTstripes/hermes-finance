"""Synthetic R08-02 portfolio and account-scope XIRR coverage."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExternalFlowClassification,
    PerformanceScope,
    XirrAvailabilityStatus,
    XirrCashFlow,
    XirrQuality,
    XirrReasonCode,
    calculate_xirr,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
    InvestmentCashFlow,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import (
    attest_cash_boundary_history,
    create_cash_boundary_coverage,
)
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import (
    create_external_flow,
    create_external_transfer_link,
)
from hermes_finance.services.in_kind_boundary_coverage import attest_in_kind_boundary_history
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)
from hermes_finance.services.portfolio_xirr import (
    portfolio_xirr_for_interval,
    xirr_for_interval,
)
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

START = date(2030, 1, 31)
MID = date(2031, 1, 31)
END = date(2032, 1, 31)
# Three exact 365-day steps; the 2032 leap day makes this January 30.
END_PLUS_YEAR = date(2033, 1, 30)


def _history(
    tmp_path: Path,
    *,
    opening: str = "1000.00",
    closing: str = "1100.00",
    include_opening: bool = True,
    include_closing: bool = True,
    close_months: bool = True,
) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-02.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    opening_month = create_reporting_month(
        session,
        year=2030,
        month=1,
        snapshot_date=START,
    )
    closing_month = create_reporting_month(
        session,
        year=2032,
        month=1,
        snapshot_date=END,
    )
    account = create_account(
        session,
        name="Synthetic XIRR Account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic XIRR Bond",
        instrument_type="bond",
    )
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()
    create_cash_boundary_coverage(
        session,
        account_id=account.id,
        covered_from=START,
        covered_to=END,
    )
    attest_in_kind_boundary_history(
        session, account_id=account.id, covered_from=START, covered_to=END
    )

    boundary_rows = (
        (opening_month.id, opening, include_opening, "Synthetic opening"),
        (closing_month.id, closing, include_closing, "Synthetic closing"),
    )
    for month_id, amount, included, label in boundary_rows:
        if not included:
            continue
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit="0.00",
            market_price_per_unit=amount,
            price_date=START if month_id == opening_month.id else END,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name=f"{label} deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name=f"{label} cash",
            amount="0.00",
        )

    if close_months:
        close_reporting_month(session, opening_month.id)
        close_reporting_month(session, closing_month.id)
    return session, database, opening_month.id, closing_month.id, account.id


def _assert_rate(result: object, expected: str) -> None:
    assert result.availability is XirrAvailabilityStatus.AVAILABLE
    assert result.quality is XirrQuality.EXACT
    assert result.annualized_rate is not None
    assert abs(result.annualized_rate - Decimal(expected)) < Decimal("1e-24")


def test_xirr_solver_matches_independent_positive_and_negative_vectors() -> None:
    positive = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 110_000),
        )
    )
    _assert_rate(positive, "0.10")

    negative = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 90_000),
        )
    )
    _assert_rate(negative, "-0.10")


def test_xirr_solver_handles_multiple_contributions_and_withdrawal() -> None:
    contributions = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, -50_000),
            XirrCashFlow(END, 176_000),
        )
    )
    _assert_rate(contributions, "0.10")

    withdrawal = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 20_000),
            XirrCashFlow(END, 99_000),
        )
    )
    _assert_rate(withdrawal, "0.10")


def test_xirr_solver_coalesces_same_day_flows_and_rejects_missing_root() -> None:
    same_day = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(START, 10_000),
            XirrCashFlow(MID, 99_000),
        )
    )
    _assert_rate(same_day, "0.10")

    no_root = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(END, -1),
        )
    )
    assert no_root.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert no_root.reason_codes == (XirrReasonCode.NO_VALID_ROOT.value,)


def test_xirr_solver_fails_closed_for_multiple_roots_and_convergence_limit() -> None:
    multiple_roots = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 600_000),
            XirrCashFlow(END, -800_000),
        )
    )
    assert multiple_roots.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert multiple_roots.reason_codes == (XirrReasonCode.ROOT_AMBIGUITY.value,)

    convergence = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(END, 110_000),
        ),
        max_iterations=1,
    )
    assert convergence.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert convergence.reason_codes == (XirrReasonCode.CONVERGENCE_FAILED.value,)


def test_xirr_solver_rejects_multiple_roots_hidden_inside_scan_cell() -> None:
    hidden_multiple_roots = calculate_xirr(
        (
            XirrCashFlow(START, -72_000),
            XirrCashFlow(MID, 530_000),
            XirrCashFlow(END, -950_000),
            XirrCashFlow(END_PLUS_YEAR, 500_000),
        )
    )
    assert hidden_multiple_roots.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert hidden_multiple_roots.reason_codes == (XirrReasonCode.ROOT_AMBIGUITY.value,)


def test_portfolio_xirr_applies_contribution_and_withdrawal_signs(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, account_id = _history(
        tmp_path,
        closing="1760.00",
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="500.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        _assert_rate(result, "0.10")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_withdrawal_is_positive_investor_receipt(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, account_id = _history(
        tmp_path,
        closing="990.00",
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="200.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        _assert_rate(result, "0.10")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_keeps_no_valid_root_unavailable(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, closing="0.00")
    try:
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert result.reason_codes == (XirrReasonCode.NO_VALID_ROOT.value,)
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_keeps_incomplete_opening_unavailable(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, include_opening=False)
    try:
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert "not_computable_scope_coverage_incomplete" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_api_exposes_annualized_value_and_period(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, closing="1100.00")
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/xirr",
                params={"start_date": START.isoformat(), "end_date": END.isoformat()},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["metric"] == "xirr"
        assert body["scope"] == "portfolio"
        assert body["availability"] == "available"
        assert body["quality"] == "exact"
        assert body["annualized"] is True
        assert body["value_unit"] == "percentage_points"
        assert abs(Decimal(body["value"]) - Decimal("4.880884817015154699145351366")) < Decimal(
            "1e-20"
        )
        assert body["period"] == {
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
        }
        assert body["reason_codes"] == []
    finally:
        database.engine.dispose()


def test_portfolio_xirr_api_exposes_honest_unavailable_state(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, closing="0.00")
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/xirr",
                params={"start_date": START.isoformat(), "end_date": END.isoformat()},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["value"] is None
        assert body["availability"] == "not_computable"
        assert body["quality"] == "unavailable"
        assert body["reason_codes"] == [XirrReasonCode.NO_VALID_ROOT.value]
    finally:
        database.engine.dispose()


# ---------------------------------------------------------------------------
# Account-scope coverage for #146.
#
# Every numeric expectation below is hand-derivable from the exact 365-day
# steps declared above: START -> MID is one year and START -> END is two
# years, so 1.10 ** 1 == 1.1 and 1.10 ** 2 == 1.21.
# ---------------------------------------------------------------------------

COVER_FROM = date(2029, 1, 1)
COVER_TO = date(2033, 1, 1)


def _attest_boundary_evidence(session: Session, account_id: int) -> None:
    """Persist the affirmative coverage an exact metric requires for one account."""

    create_cash_boundary_coverage(
        session,
        account_id=account_id,
        covered_from=COVER_FROM,
        covered_to=COVER_TO,
    )
    attest_in_kind_boundary_history(
        session,
        account_id=account_id,
        covered_from=COVER_FROM,
        covered_to=COVER_TO,
    )


def _reattest_cash_boundary_evidence(session: Session, account_id: int) -> None:
    """Reaffirm cash history after a material flow mutation invalidated it."""

    attest_cash_boundary_history(
        session,
        account_id=account_id,
        covered_from=COVER_FROM,
        covered_to=COVER_TO,
    )


def _multi_account_history(
    tmp_path: Path,
    *,
    database_name: str,
    opening_values: tuple[str, ...],
    closing_values: tuple[str, ...],
    include_opening: bool = True,
    close_months: bool = True,
) -> tuple[Session, object, int, int, tuple[int, ...]]:
    """Build one or more in-scope brokerage accounts with explicit boundaries."""

    database = create_database(tmp_path / database_name)
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    opening_month = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    closing_month = create_reporting_month(session, year=2032, month=1, snapshot_date=END)
    instrument = create_instrument(
        session,
        name="Synthetic XIRR Bond",
        instrument_type="bond",
    )
    accounts = tuple(
        create_account(
            session,
            name=f"Synthetic XIRR Account {index + 1}",
            account_type=AccountType.BROKERAGE,
        )
        for index in range(len(opening_values))
    )
    for account in accounts:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
    session.commit()
    for account in accounts:
        _attest_boundary_evidence(session, account.id)

    boundaries = (
        (opening_month.id, START, opening_values, include_opening),
        (closing_month.id, END, closing_values, True),
    )
    for month_id, price_date, values, included in boundaries:
        if not included:
            continue
        for account, amount in zip(accounts, values, strict=True):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="0.00",
                market_price_per_unit=amount,
                price_date=price_date,
            )
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account.id,
                name=f"Synthetic deposit {account.id}",
                deposit_type="deposit",
                balance="0.00",
                annual_rate="0.00",
            )
            create_cash_balance(
                session,
                reporting_month_id=month_id,
                account_id=account.id,
                name=f"Synthetic cash {account.id}",
                amount="0.00",
            )

    if close_months:
        close_reporting_month(session, opening_month.id)
        close_reporting_month(session, closing_month.id)
    return (
        session,
        database,
        opening_month.id,
        closing_month.id,
        tuple(account.id for account in accounts),
    )


def test_account_xirr_without_external_flows_is_exact(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
    )
    try:
        result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        # 1000.00 -> 1210.00 over two exact 365-day steps is 1.21 == 1.10 ** 2.
        _assert_rate(result, "0.10")
        assert result.scope is PerformanceScope.ACCOUNT
        assert result.account_id == account_id
    finally:
        session.close()
        database.engine.dispose()


def test_account_xirr_contribution_is_negative_investor_outflow(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-contribution.db",
        opening_values=("1000.00",),
        closing_values=("1760.00",),
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="500.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _reattest_cash_boundary_evidence(session, account_id)
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        # -1000 - 500/1.1 + 1760/1.21 == 0, and the contribution must be
        # negative for the owner: a wrong sign cannot satisfy this identity.
        _assert_rate(result, "0.10")
        assert result.account_id == account_id
    finally:
        session.close()
        database.engine.dispose()


def test_account_xirr_withdrawal_is_positive_investor_receipt(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-withdrawal.db",
        opening_values=("1000.00",),
        closing_values=("990.00",),
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="200.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        _reattest_cash_boundary_evidence(session, account_id)
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        # -1000 + 200/1.1 + 990/1.21 == 0, and the withdrawal must be a
        # positive owner receipt for this identity to hold.
        _assert_rate(result, "0.10")
        assert result.account_id == account_id
    finally:
        session.close()
        database.engine.dispose()


def test_linked_transfer_is_withdrawal_for_source_and_contribution_for_target(
    tmp_path: Path,
) -> None:
    session, database, opening_month_id, closing_month_id, (source_id, target_id) = (
        _multi_account_history(
            tmp_path,
            database_name="r08-02-account-transfer.db",
            opening_values=("1000.00", "1000.00"),
            closing_values=("1100.00", "1320.00"),
            close_months=False,
        )
    )
    try:
        link = create_external_transfer_link(session, transfer_key="synthetic-account-transfer")
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=source_id,
            event_date=MID,
            boundary_amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=target_id,
            event_date=MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        _reattest_cash_boundary_evidence(session, source_id)
        _reattest_cash_boundary_evidence(session, target_id)
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)

        source = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=source_id,
        )
        target = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=target_id,
        )
        portfolio = xirr_for_interval(session, start_date=START, end_date=END)

        # source:  -1000 + 100/1.1 + 1100/1.21 == 0 -> the leg is a receipt.
        _assert_rate(source, "0.10")
        # target:  -1000 - 100/1.1 + 1320/1.21 == 0 -> the leg is an outflow.
        _assert_rate(target, "0.10")
        # portfolio: -2000 + 2420/1.21 == 0 -> both legs stay internal.
        _assert_rate(portfolio, "0.10")

        source_flows = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=source_id,
        ).external_flows.flows
        target_flows = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=target_id,
        ).external_flows.flows
        portfolio_flows = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        ).external_flows.flows

        assert [flow.classification for flow in source_flows] == [
            ExternalFlowClassification.EXTERNAL_WITHDRAWAL
        ]
        assert [flow.classification for flow in target_flows] == [
            ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        ]
        assert len(portfolio_flows) == 2
        assert all(
            flow.classification is ExternalFlowClassification.INTERNAL_TRANSFER
            for flow in portfolio_flows
        )
    finally:
        session.close()
        database.engine.dispose()


def test_foreign_account_flow_is_excluded_from_account_xirr(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, (measured_id, other_id) = (
        _multi_account_history(
            tmp_path,
            database_name="r08-02-account-foreign.db",
            opening_values=("1000.00", "1000.00"),
            closing_values=("1210.00", "1600.00"),
            close_months=False,
        )
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=other_id,
            event_date=MID,
            boundary_amount="500.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _reattest_cash_boundary_evidence(session, other_id)
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)

        account_result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=measured_id,
        )
        portfolio_result = xirr_for_interval(session, start_date=START, end_date=END)

        # The measured account has no flows of its own: 1.10 ** 2 exactly.
        # Leaking the other account's -500.00 would break this identity.
        _assert_rate(account_result, "0.10")
        assert (
            performance_availability_for_interval(
                session,
                start_date=START,
                end_date=END,
                scope="account",
                account_id=measured_id,
            ).external_flows.flows
            == ()
        )
        assert [
            flow.account_id
            for flow in performance_availability_for_interval(
                session,
                start_date=START,
                end_date=END,
                scope="portfolio",
            ).external_flows.flows
        ] == [other_id]
        assert portfolio_result.is_available
        assert portfolio_result.annualized_rate != account_result.annualized_rate
    finally:
        session.close()
        database.engine.dispose()


def test_account_xirr_fails_closed_without_account_valuation_boundaries(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-no-boundary.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
    )
    try:
        missing_opening = xirr_for_interval(
            session,
            start_date=date(2030, 1, 30),
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert missing_opening.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert missing_opening.value is None
        assert missing_opening.reason_codes == ("not_computable_opening_valuation_missing",)

        missing_closing = xirr_for_interval(
            session,
            start_date=START,
            end_date=date(2030, 3, 31),
            scope="account",
            account_id=account_id,
        )
        assert missing_closing.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert missing_closing.value is None
        assert missing_closing.reason_codes == ("not_computable_closing_valuation_missing",)
    finally:
        session.close()
        database.engine.dispose()


def test_account_xirr_fails_closed_when_account_components_are_absent(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-empty-components.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
        include_opening=False,
    )
    try:
        result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert result.reason_codes == ("not_computable_scope_coverage_incomplete",)
        assert result.scope is PerformanceScope.ACCOUNT
        assert result.account_id == account_id
    finally:
        session.close()
        database.engine.dispose()


def test_account_xirr_keeps_non_authoritative_flow_reason(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-non-authoritative.db",
        opening_values=("1000.00",),
        closing_values=("1760.00",),
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="500.00",
            direction="contribution",
            kind="external_contribution",
        )
        _reattest_cash_boundary_evidence(session, account_id)
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert "not_computable_scope_membership_history_missing" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_account_xirr_fails_closed_on_legacy_account_boundary_rows(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-legacy.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
        close_months=False,
    )
    try:
        session.add(
            InvestmentCashFlow(
                reporting_month_id=closing_month_id,
                account_id=account_id,
                instrument_id=None,
                flow_type="deposit",
                event_date=MID,
                gross_amount_kopecks=10_000,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
                net_amount_kopecks=10_000,
                currency="RUB",
                source="synthetic-legacy",
            )
        )
        session.commit()
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert "not_computable_external_flows_incomplete" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_result_identity_is_unchanged(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-portfolio-identity.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
    )
    try:
        generic = xirr_for_interval(session, start_date=START, end_date=END)
        explicit = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
            account_id=None,
        )
        compatibility = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        _assert_rate(generic, "0.10")
        assert generic.scope is PerformanceScope.PORTFOLIO
        assert generic.account_id is None
        assert generic == explicit == compatibility
        assert account_id > 0
    finally:
        session.close()
        database.engine.dispose()


def test_xirr_scope_and_account_id_validation(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-scope-validation.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
    )
    try:
        with pytest.raises(ValueError, match="account_id is required"):
            xirr_for_interval(session, start_date=START, end_date=END, scope="account")
        with pytest.raises(ValueError, match="account_id must be omitted"):
            xirr_for_interval(
                session,
                start_date=START,
                end_date=END,
                scope="portfolio",
                account_id=account_id,
            )
        with pytest.raises(ValueError, match="unsupported XIRR scope"):
            xirr_for_interval(session, start_date=START, end_date=END, scope="asset_class")
        # The rejected calls returned no value-bearing result: the accepted
        # account combination still produces the exact reference value.
        accepted = xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=account_id,
        )
        _assert_rate(accepted, "0.10")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_api_supports_explicit_account_scope(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-account-api.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
    )
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/xirr",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "account",
                    "account_id": account_id,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["metric"] == "xirr"
        assert body["scope"] == "account"
        assert body["account_id"] == account_id
        assert body["availability"] == "available"
        assert body["quality"] == "exact"
        assert abs(Decimal(body["value"]) - Decimal("10")) < Decimal("1e-20")
        assert body["period"] == {
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
        }
        assert body["reason_codes"] == []
    finally:
        database.engine.dispose()


def test_portfolio_xirr_api_rejects_inconsistent_scope_arguments(tmp_path: Path) -> None:
    session, database, _, _, (account_id,) = _multi_account_history(
        tmp_path,
        database_name="r08-02-scope-api.db",
        opening_values=("1000.00",),
        closing_values=("1210.00",),
    )
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            missing_account_id = client.get(
                "/api/performance/xirr",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "account",
                },
            )
            unexpected_account_id = client.get(
                "/api/performance/xirr",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "portfolio",
                    "account_id": account_id,
                },
            )
            unsupported_scope = client.get(
                "/api/performance/xirr",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "asset_class",
                },
            )
        for response in (missing_account_id, unexpected_account_id, unsupported_scope):
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "unprocessable"
    finally:
        database.engine.dispose()
