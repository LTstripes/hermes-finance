"""Synthetic PERF-H2c async-transfer transit and reconciliation regressions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, PerformanceScope
from hermes_finance.persistence import AccountPerformanceScopeMembership, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import create_cash_boundary_coverage
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
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month
from hermes_finance.services.transfer_reconciliation import (
    create_transfer_reconciliation_evidence,
)

START = date(2030, 1, 31)
END = date(2030, 2, 28)
MID_CLOSING = date(2030, 2, 12)


def _environment(
    tmp_path: Path,
    *,
    start_date: date = START,
    end_date: date = END,
) -> tuple[Session, object, dict[int, int], tuple[int, int]]:
    database = create_database(tmp_path / "r08-h2c.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    start_month = create_reporting_month(
        session,
        year=start_date.year,
        month=start_date.month,
        snapshot_date=start_date,
    )
    end_month = create_reporting_month(
        session,
        year=end_date.year,
        month=end_date.month,
        snapshot_date=end_date,
    )
    accounts = tuple(
        create_account(
            session, name=f"Synthetic transfer account {index}", account_type=AccountType.BROKERAGE
        )
        for index in (1, 2)
    )
    instrument = create_instrument(
        session,
        name="Synthetic transfer instrument",
        instrument_type="bond",
    )
    for account in accounts:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        for month, snapshot_date in (
            (start_month, start_date),
            (end_month, end_date),
        ):
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="1000.00",
                market_price_per_unit="1000.00",
                price_date=snapshot_date,
            )
            create_deposit_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic transfer deposit",
                deposit_type="deposit",
                balance="0.00",
                annual_rate="0.00",
            )
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic transfer cash",
                amount="0.00",
            )
        session.commit()
        create_cash_boundary_coverage(
            session,
            account_id=account.id,
            covered_from=start_date,
            covered_to=end_date,
        )
    return (
        session,
        database,
        {start_month.id: start_month.id, end_month.id: end_month.id},
        (accounts[0].id, accounts[1].id),
    )


def _close(session: Session, month_ids: dict[int, int]) -> None:
    for month_id in month_ids.values():
        close_reporting_month(session, month_id)


def _leg(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    event_date: date,
    amount: str,
    direction: str,
    currency: str = "RUB",
    transfer_link_id: int,
):
    return create_external_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        event_date=event_date,
        boundary_amount=amount,
        direction=direction,
        kind=("external_withdrawal" if direction == "withdrawal" else "external_contribution"),
        currency=currency,
        scope_membership="stable_in_scope",
        transfer_link_id=transfer_link_id,
    )


def _transfer(
    session: Session,
    month_ids: dict[int, int],
    accounts: tuple[int, int],
    *,
    source_date: date,
    destination_date: date,
    source_amount: str = "1000.00",
    destination_amount: str = "1000.00",
    source_currency: str = "RUB",
    destination_currency: str = "RUB",
):
    link = create_external_transfer_link(
        session, transfer_key=f"transfer-{source_date}-{destination_date}"
    )
    source = _leg(
        session,
        month_id=_month_id_for(month_ids, source_date),
        account_id=accounts[0],
        event_date=source_date,
        amount=source_amount,
        direction="withdrawal",
        currency=source_currency,
        transfer_link_id=link.id,
    )
    destination = _leg(
        session,
        month_id=_month_id_for(month_ids, destination_date),
        account_id=accounts[1],
        event_date=destination_date,
        amount=destination_amount,
        direction="contribution",
        currency=destination_currency,
        transfer_link_id=link.id,
    )
    return link, source, destination


def _month_id_for(month_ids: dict[int, int], event_date: date) -> int:
    """The fixture has one reporting month per calendar month."""

    return min(month_ids) if event_date.month == 1 else max(month_ids)


def test_required_closing_valuation_inside_transit_blocks_both_metrics(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path, end_date=MID_CLOSING)
    try:
        link = create_external_transfer_link(session, transfer_key="closing-inside-transit")
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 2, 10),
            amount="1000.00",
            direction="withdrawal",
            transfer_link_id=link.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 15),
            amount="1000.00",
            direction="contribution",
            transfer_link_id=link.id,
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=MID_CLOSING,
            scope=PerformanceScope.PORTFOLIO,
        )
        assert not result.xirr.is_available
        assert not result.twrr.is_available
        assert "not_computable_transfer_in_transit_unvalued" in result.xirr.reason_codes
        assert "not_computable_transfer_in_transit_unvalued" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_transit_without_required_valuation_intersection_does_not_block(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="inside-interval")
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 2, 10),
            amount="1000.00",
            direction="withdrawal",
            transfer_link_id=link.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 15),
            amount="1000.00",
            direction="contribution",
            transfer_link_id=link.id,
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert result.xirr.is_available
        assert result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_unrelated_twrr_boundary_inside_transit_only_blocks_twrr(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="unrelated-boundary")
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 2, 10),
            amount="1000.00",
            direction="withdrawal",
            transfer_link_id=link.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 15),
            amount="1000.00",
            direction="contribution",
            transfer_link_id=link.id,
        )
        create_external_flow(
            session,
            reporting_month_id=max(month_ids),
            account_id=accounts[0],
            event_date=MID_CLOSING,
            boundary_amount="10.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert "not_computable_transfer_in_transit_unvalued" in result.twrr.reason_codes
        assert "not_computable_transfer_in_transit_unvalued" not in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_unequal_legs_require_transfer_specific_evidence(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        _transfer(
            session,
            month_ids,
            accounts,
            source_date=date(2030, 2, 10),
            destination_date=date(2030, 2, 15),
            source_amount="1000.00",
            destination_amount="999.00",
        )
        _close(session, month_ids)
        unavailable = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert "not_computable_transfer_reconciliation_incomplete" in unavailable.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()

    reconciled_session, reconciled_database, reconciled_month_ids, reconciled_accounts = (
        _environment(tmp_path / "reconciled")
    )
    try:
        reconciled_link, _source, _destination = _transfer(
            reconciled_session,
            reconciled_month_ids,
            reconciled_accounts,
            source_date=date(2030, 2, 10),
            destination_date=date(2030, 2, 15),
            source_amount="1000.00",
            destination_amount="999.00",
        )
        create_transfer_reconciliation_evidence(
            reconciled_session,
            transfer_link_id=reconciled_link.id,
            kind="internal_fee",
            amount="1.00",
            currency="RUB",
            source="synthetic-broker-statement",
            evidence_reference="fee-transfer-specific-1",
        )
        _close(reconciled_session, reconciled_month_ids)
        reconciled = performance_availability_for_interval(
            reconciled_session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert (
            "not_computable_transfer_reconciliation_incomplete" not in reconciled.xirr.reason_codes
        )
        assert reconciled.xirr.is_available
    finally:
        reconciled_session.close()
        reconciled_database.engine.dispose()


def test_destination_gain_is_not_reconciled_as_internal_fee(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        link, *_ = _transfer(
            session,
            month_ids,
            accounts,
            source_date=date(2030, 2, 10),
            destination_date=date(2030, 2, 15),
            source_amount="999.00",
            destination_amount="1000.00",
        )
        create_transfer_reconciliation_evidence(
            session,
            transfer_link_id=link.id,
            kind="internal_fee",
            amount="1.00",
            currency="RUB",
            source="synthetic-broker-statement",
            evidence_reference="fee-cannot-explain-gain",
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert not result.xirr.is_available
        assert "not_computable_transfer_reconciliation_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_evidence_for_one_overlapping_transfer_does_not_reconcile_another(
    tmp_path: Path,
) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        first, *_ = _transfer(
            session,
            month_ids,
            accounts,
            source_date=date(2030, 2, 10),
            destination_date=date(2030, 2, 15),
            source_amount="1000.00",
            destination_amount="999.00",
        )
        second = create_external_transfer_link(session, transfer_key="overlap-2")
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 2, 11),
            amount="500.00",
            direction="withdrawal",
            transfer_link_id=second.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 16),
            amount="499.00",
            direction="contribution",
            transfer_link_id=second.id,
        )
        create_transfer_reconciliation_evidence(
            session,
            transfer_link_id=first.id,
            kind="internal_tax",
            amount="1.00",
            currency="RUB",
            source="synthetic-tax-ledger",
            evidence_reference="tax-transfer-1",
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert not result.xirr.is_available
        assert "not_computable_transfer_reconciliation_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_transfer_legs_outside_interval_still_block_transit_at_opening(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="outside-interval")
        _leg(
            session,
            month_id=min(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 1, 15),
            amount="1000.00",
            direction="withdrawal",
            transfer_link_id=link.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 15),
            amount="1000.00",
            direction="contribution",
            transfer_link_id=link.id,
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert not result.xirr.is_available
        assert "not_computable_transfer_in_transit_unvalued" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_transit_leg_outside_interval_checks_effective_membership(tmp_path: Path) -> None:
    closing_date = date(2030, 2, 1)
    session, database, month_ids, accounts = _environment(tmp_path, end_date=closing_date)
    try:
        membership = session.scalar(
            select(AccountPerformanceScopeMembership).where(
                AccountPerformanceScopeMembership.account_id == accounts[0]
            )
        )
        assert membership is not None
        membership.effective_to = date(2030, 1, 14)
        session.add(
            AccountPerformanceScopeMembership(
                account_id=accounts[0],
                effective_from=date(2030, 1, 15),
                effective_to=date(2030, 1, 20),
                include_in_returns=False,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=accounts[0],
                effective_from=date(2030, 1, 21),
                include_in_returns=True,
            )
        )
        session.commit()

        link = create_external_transfer_link(session, transfer_key="outside-membership-check")
        _leg(
            session,
            month_id=min(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 1, 15),
            amount="1000.00",
            direction="withdrawal",
            transfer_link_id=link.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 15),
            amount="1000.00",
            direction="contribution",
            transfer_link_id=link.id,
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=closing_date,
            scope=PerformanceScope.PORTFOLIO,
        )
        assert not result.xirr.is_available
        assert not result.twrr.is_available
        assert "not_computable_scope_coverage_incomplete" in result.xirr.reason_codes
        assert "not_computable_scope_coverage_incomplete" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_account_scope_does_not_inherit_portfolio_transit_block(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path, end_date=MID_CLOSING)
    try:
        link = create_external_transfer_link(session, transfer_key="account-scope")
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[0],
            event_date=date(2030, 2, 10),
            amount="1000.00",
            direction="withdrawal",
            transfer_link_id=link.id,
        )
        _leg(
            session,
            month_id=max(month_ids),
            account_id=accounts[1],
            event_date=date(2030, 2, 15),
            amount="1000.00",
            direction="contribution",
            transfer_link_id=link.id,
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=MID_CLOSING,
            scope="account",
            account_id=accounts[0],
        )
        assert "not_computable_transfer_in_transit_unvalued" not in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_fx_evidence_does_not_bypass_currency_completeness(tmp_path: Path) -> None:
    session, database, month_ids, accounts = _environment(tmp_path)
    try:
        link, *_ = _transfer(
            session,
            month_ids,
            accounts,
            source_date=date(2030, 2, 10),
            destination_date=date(2030, 2, 15),
            source_currency="EUR",
            destination_currency="USD",
        )
        create_transfer_reconciliation_evidence(
            session,
            transfer_link_id=link.id,
            kind="fx_conversion_spread",
            amount="1.00",
            currency="EUR",
            source="synthetic-fx-statement",
            evidence_reference="fx-transfer-1",
        )
        _close(session, month_ids)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )
        assert "not_computable_currency_conversion_incomplete" in result.xirr.reason_codes
        assert "not_computable_transfer_reconciliation_incomplete" not in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()
