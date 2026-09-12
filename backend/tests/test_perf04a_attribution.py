"""PERF04A exact selected-scope value-bridge contract vectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, PerformanceAvailabilityStatus, PerformanceScope
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
)
from hermes_finance.persistence import (
    CashBoundaryCoverage as CashBoundaryCoverageRecord,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import attest_cash_boundary_history
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import (
    create_external_flow,
    create_external_transfer_link,
)
from hermes_finance.services.in_kind_boundary_coverage import (
    attest_in_kind_boundary_history,
    create_in_kind_movement,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.performance_attribution import (
    perf04a_bridge_prerequisites,
    performance_attribution_for_interval,
)
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

START = date(2030, 1, 31)
END = date(2030, 2, 28)
MID = date(2030, 2, 12)


@dataclass(slots=True)
class _Fixture:
    session: Session
    database: object
    january_id: int
    february_id: int
    account_ids: tuple[int, ...]
    instrument_id: int


def _environment(
    tmp_path: Path,
    *,
    account_values: tuple[tuple[str, str], ...] = (("1000.00", "1000.00"),),
) -> _Fixture:
    database = create_database(tmp_path / "perf04a.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    instrument = create_instrument(
        session,
        name="Synthetic PERF04A Instrument",
        instrument_type="bond",
    )
    accounts = tuple(
        create_account(
            session,
            name=f"Synthetic PERF04A Account {index}",
            account_type=AccountType.BROKERAGE,
        )
        for index in range(1, len(account_values) + 1)
    )
    for account, (opening_value, closing_value) in zip(accounts, account_values, strict=True):
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        for month, value in (
            (january, opening_value),
            (february, closing_value),
        ):
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="1000.00",
                market_price_per_unit=value,
                price_date=month.snapshot_date,
            )
            create_deposit_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic PERF04A Deposit",
                deposit_type="deposit",
                balance="0.00",
                annual_rate="0.00",
            )
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic PERF04A Cash",
                amount="0.00",
            )
    session.commit()
    for account in accounts:
        attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=END,
        )
        attest_in_kind_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=END,
        )
    return _Fixture(
        session=session,
        database=database,
        january_id=january.id,
        february_id=february.id,
        account_ids=tuple(account.id for account in accounts),
        instrument_id=instrument.id,
    )


def _close(fixture: _Fixture) -> None:
    close_reporting_month(fixture.session, fixture.january_id)
    close_reporting_month(fixture.session, fixture.february_id)


def _finish(fixture: _Fixture) -> None:
    fixture.session.close()
    fixture.database.engine.dispose()


def _create_flow(
    fixture: _Fixture,
    *,
    account_id: int,
    event_date: date,
    amount: str,
    direction: str,
    kind: str,
    transfer_link_id: int | None = None,
    currency: str = "RUB",
) -> object:
    flow = create_external_flow(
        fixture.session,
        reporting_month_id=(fixture.january_id if event_date <= START else fixture.february_id),
        account_id=account_id,
        event_date=event_date,
        boundary_amount=amount,
        direction=direction,
        kind=kind,
        scope_membership="stable_in_scope",
        transfer_link_id=transfer_link_id,
        currency=currency,
    )
    attest_cash_boundary_history(
        fixture.session,
        account_id=account_id,
        covered_from=START,
        covered_to=END,
    )
    return flow


def _transfer(
    fixture: _Fixture,
    *,
    source_date: date = MID,
    destination_date: date = MID,
    source_amount: str = "100.00",
    destination_amount: str = "100.00",
) -> tuple[object, object, object]:
    source_account, destination_account = fixture.account_ids[:2]
    link = create_external_transfer_link(
        fixture.session,
        transfer_key=f"perf04a-{source_date}-{destination_date}-{source_amount}-{destination_amount}",
    )
    source = _create_flow(
        fixture,
        account_id=source_account,
        event_date=source_date,
        amount=source_amount,
        direction="withdrawal",
        kind="external_withdrawal",
        transfer_link_id=link.id,
    )
    destination = _create_flow(
        fixture,
        account_id=destination_account,
        event_date=destination_date,
        amount=destination_amount,
        direction="contribution",
        kind="external_contribution",
        transfer_link_id=link.id,
    )
    return link, source, destination


def _bridge(
    fixture: _Fixture,
    *,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
    start_date: date = START,
    end_date: date = END,
):
    return performance_attribution_for_interval(
        fixture.session,
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        account_id=account_id,
    )


def test_no_flow_bridge_is_exact_and_explicit_zero(tmp_path: Path) -> None:
    fixture = _environment(tmp_path, account_values=(("1000.00", "1160.00"),))
    try:
        _close(fixture)
        result = _bridge(fixture)

        assert result.is_available
        assert result.value is not None
        assert result.value.kopecks == 16_000
        assert result.external_flow_summary.contributions is not None
        assert result.external_flow_summary.contributions.kopecks == 0
        assert result.external_flow_summary.withdrawals is not None
        assert result.external_flow_summary.withdrawals.kopecks == 0
        assert result.external_flow_summary.signed_total is not None
        assert result.external_flow_summary.signed_total.kopecks == 0
        assert result.reason_codes == ()
    finally:
        _finish(fixture)


def test_contribution_withdrawal_bridge_uses_exact_signed_flow_total_and_api(
    tmp_path: Path,
) -> None:
    fixture = _environment(tmp_path, account_values=(("1000.00", "1333.50"),))
    try:
        _create_flow(
            fixture,
            account_id=fixture.account_ids[0],
            event_date=date(2030, 2, 10),
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        _create_flow(
            fixture,
            account_id=fixture.account_ids[0],
            event_date=date(2030, 2, 20),
            amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
        )
        _close(fixture)
        result = _bridge(fixture)
        assert result.is_available
        assert result.value is not None and result.value.kopecks == 28_350
        assert result.external_flow_summary.signed_total is not None
        assert result.external_flow_summary.signed_total.kopecks == 5_000

        fixture.session.close()
        with TestClient(create_app(fixture.database)) as client:
            response = client.get(
                "/api/performance/attribution",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "portfolio",
                },
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {
            "contract": "PERF04A",
            "contract_version": 1,
            "metric": "value_change_after_external_flows",
            "grain": "selected_scope",
            "scope": "portfolio",
            "account_id": None,
            "period": {"start_date": START.isoformat(), "end_date": END.isoformat()},
            "performance_currency": "RUB",
            "availability": "available",
            "quality": "exact",
            "opening_value": {"amount": "1000.00", "currency": "RUB"},
            "closing_value": {"amount": "1333.50", "currency": "RUB"},
            "value": {"amount": "283.50", "currency": "RUB"},
            "external_flow_summary": {
                "contributions": {"amount": "100.00", "currency": "RUB"},
                "withdrawals": {"amount": "50.00", "currency": "RUB"},
                "signed_total": {"amount": "50.00", "currency": "RUB"},
            },
            "evidence": {
                "opening_valuation": {"availability": "available", "reason_codes": []},
                "closing_valuation": {"availability": "available", "reason_codes": []},
                "scope_membership": {"status": "complete", "reason_codes": []},
                "cash_boundary_coverage": {"status": "complete", "reason_codes": []},
                "in_kind_boundary_coverage": {"status": "complete", "reason_codes": []},
                "external_flows": {"status": "complete", "reason_codes": []},
            },
            "reason_codes": [],
        }
    finally:
        fixture.database.engine.dispose()


@pytest.mark.parametrize(
    ("flow_type", "opening", "closing", "expected"),
    (
        ("coupon", "1000.00", "1020.00", 2_000),
        ("redemption", "1000.00", "1000.00", 0),
        ("commission", "1000.00", "987.00", -1_300),
    ),
)
def test_internal_income_principal_and_cost_are_not_injected_twice(
    tmp_path: Path,
    flow_type: str,
    opening: str,
    closing: str,
    expected: int,
) -> None:
    fixture = _environment(tmp_path, account_values=((opening, closing),))
    try:
        create_investment_cash_flow(
            fixture.session,
            reporting_month_id=fixture.february_id,
            account_id=fixture.account_ids[0],
            instrument_id=fixture.instrument_id,
            flow_type=flow_type,
            event_date=MID,
            gross_amount=(
                "20.00"
                if flow_type == "coupon"
                else "100.00"
                if flow_type == "redemption"
                else "13.00"
            ),
            net_amount=(
                "20.00"
                if flow_type == "coupon"
                else "100.00"
                if flow_type == "redemption"
                else "13.00"
            ),
            source="synthetic-perf04a",
        )
        _close(fixture)
        result = _bridge(fixture)
        assert result.is_available
        assert result.value is not None and result.value.kopecks == expected
    finally:
        _finish(fixture)


def test_linked_transfer_is_internal_for_portfolio_and_selected_leg_for_account(
    tmp_path: Path,
) -> None:
    fixture = _environment(
        tmp_path,
        account_values=(("1000.00", "900.00"), ("500.00", "600.00")),
    )
    try:
        _transfer(fixture)
        _close(fixture)
        portfolio = _bridge(fixture)
        source = _bridge(
            fixture,
            scope=PerformanceScope.ACCOUNT,
            account_id=fixture.account_ids[0],
        )
        destination = _bridge(
            fixture,
            scope=PerformanceScope.ACCOUNT,
            account_id=fixture.account_ids[1],
        )

        assert portfolio.is_available and portfolio.value is not None
        assert portfolio.value.kopecks == 0
        assert portfolio.external_flow_summary.signed_total is not None
        assert portfolio.external_flow_summary.signed_total.kopecks == 0
        assert source.is_available and source.value is not None and source.value.kopecks == 0
        assert destination.is_available and destination.value is not None
        assert destination.value.kopecks == 0
        assert source.external_flow_summary.signed_total is not None
        assert source.external_flow_summary.signed_total.kopecks == -10_000
        assert destination.external_flow_summary.signed_total is not None
        assert destination.external_flow_summary.signed_total.kopecks == 10_000
    finally:
        _finish(fixture)


def test_unequal_portfolio_transfer_requires_reconciliation_but_account_leg_does_not(
    tmp_path: Path,
) -> None:
    fixture = _environment(
        tmp_path,
        account_values=(("1000.00", "900.00"), ("500.00", "600.00")),
    )
    try:
        _transfer(fixture, source_amount="100.00", destination_amount="99.00")
        _close(fixture)
        portfolio = _bridge(fixture)
        source = _bridge(
            fixture,
            scope=PerformanceScope.ACCOUNT,
            account_id=fixture.account_ids[0],
        )

        assert not portfolio.is_available
        assert portfolio.value is None
        assert "not_computable_transfer_reconciliation_incomplete" in portfolio.reason_codes
        assert source.is_available and source.value is not None and source.value.kopecks == 0
    finally:
        _finish(fixture)


def test_async_transfer_at_intermediate_twrr_boundary_does_not_block_bridge(
    tmp_path: Path,
) -> None:
    fixture = _environment(
        tmp_path,
        account_values=(("1000.00", "1000.00"), ("500.00", "500.00")),
    )
    try:
        _transfer(
            fixture,
            source_date=date(2030, 2, 10),
            destination_date=date(2030, 2, 15),
        )
        _create_flow(
            fixture,
            account_id=fixture.account_ids[0],
            event_date=MID,
            amount="10.00",
            direction="contribution",
            kind="external_contribution",
        )
        _close(fixture)
        r08 = performance_availability_for_interval(
            fixture.session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.PORTFOLIO,
        )
        result = _bridge(fixture)

        assert r08.xirr.is_available
        assert not r08.twrr.is_available
        assert "not_computable_transfer_in_transit_unvalued" not in result.reason_codes
        assert result.is_available
        assert result.value is not None and result.value.kopecks == -1_000
    finally:
        _finish(fixture)


def test_async_transfer_at_bridge_endpoint_fails_closed(tmp_path: Path) -> None:
    fixture = _environment(
        tmp_path,
        account_values=(("1000.00", "1000.00"), ("500.00", "500.00")),
    )
    try:
        _transfer(
            fixture,
            source_date=START,
            destination_date=date(2030, 2, 15),
        )
        _close(fixture)
        result = _bridge(fixture)
        assert not result.is_available
        assert result.value is None
        assert "not_computable_transfer_in_transit_unvalued" in result.reason_codes
    finally:
        _finish(fixture)


def test_one_sided_transfer_identity_is_unavailable_for_account_scope(tmp_path: Path) -> None:
    fixture = _environment(tmp_path)
    try:
        link = create_external_transfer_link(fixture.session, transfer_key="perf04a-one-sided")
        _create_flow(
            fixture,
            account_id=fixture.account_ids[0],
            event_date=MID,
            amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            transfer_link_id=link.id,
        )
        _close(fixture)
        result = _bridge(
            fixture,
            scope=PerformanceScope.ACCOUNT,
            account_id=fixture.account_ids[0],
        )
        assert not result.is_available
        assert result.value is None
        assert "not_computable_transfer_identity_unresolved" in result.reason_codes
    finally:
        _finish(fixture)


def test_known_in_kind_movement_is_not_computable_without_synthetic_value(tmp_path: Path) -> None:
    fixture = _environment(tmp_path)
    try:
        create_in_kind_movement(
            fixture.session,
            reporting_month_id=fixture.february_id,
            event_date=MID,
            movement_kind="external_out",
            source_account_id=fixture.account_ids[0],
            instrument_id=fixture.instrument_id,
            quantity="1",
            provenance_kind="owner_attestation",
            provenance_reference="synthetic-perf04a-inkind",
        )
        _close(fixture)
        result = _bridge(fixture)
        assert not result.is_available
        assert result.value is None
        assert "not_computable_in_kind_movement_unvalued" in result.reason_codes
        assert result.external_flow_summary.signed_total is not None
        assert result.external_flow_summary.signed_total.kopecks == 0
    finally:
        _finish(fixture)


def test_twr_boundary_missing_or_order_unknown_does_not_gate_bridge(tmp_path: Path) -> None:
    missing_fixture = _environment(tmp_path / "missing", account_values=(("1000.00", "1300.00"),))
    try:
        _create_flow(
            missing_fixture,
            account_id=missing_fixture.account_ids[0],
            event_date=MID,
            amount="200.00",
            direction="contribution",
            kind="external_contribution",
        )
        _close(missing_fixture)
        r08 = performance_availability_for_interval(
            missing_fixture.session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=missing_fixture.account_ids[0],
        )
        result = _bridge(
            missing_fixture,
            scope=PerformanceScope.ACCOUNT,
            account_id=missing_fixture.account_ids[0],
        )
        assert not r08.twrr.is_available
        assert "not_computable_valuation_boundary_missing" in r08.twrr.reason_codes
        assert result.is_available and result.value is not None
        assert result.value.kopecks == 10_000
    finally:
        _finish(missing_fixture)

    order_fixture = _environment(tmp_path / "order")
    try:
        _create_flow(
            order_fixture,
            account_id=order_fixture.account_ids[0],
            event_date=START,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        _close(order_fixture)
        r08 = performance_availability_for_interval(
            order_fixture.session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=order_fixture.account_ids[0],
        )
        result = _bridge(
            order_fixture,
            scope=PerformanceScope.ACCOUNT,
            account_id=order_fixture.account_ids[0],
        )
        assert not r08.twrr.is_available
        assert "not_computable_valuation_boundary_order_unknown" in r08.twrr.reason_codes
        assert result.is_available
        assert result.value is not None and result.value.kopecks == -10_000
        assert "not_computable_valuation_boundary_order_unknown" not in result.reason_codes
        assert result.evidence.opening_valuation.reason_codes == (
            "not_computable_valuation_boundary_order_unknown",
        )
    finally:
        _finish(order_fixture)


def test_missing_cash_coverage_is_unavailable_and_not_zero(tmp_path: Path) -> None:
    fixture = _environment(tmp_path)
    try:
        fixture.session.execute(
            delete(CashBoundaryCoverageRecord).where(
                CashBoundaryCoverageRecord.account_id.in_(fixture.account_ids)
            )
        )
        fixture.session.commit()
        _close(fixture)
        result = _bridge(fixture)
        assert not result.is_available
        assert result.value is None
        assert "not_computable_cash_boundary_coverage_unknown" not in result.reason_codes
        assert result.evidence.cash_boundary_coverage.status == "unknown"
        assert result.reason_codes == ("not_computable_external_flows_incomplete",)
    finally:
        _finish(fixture)


def test_missing_currency_evidence_is_not_converted(tmp_path: Path) -> None:
    fixture = _environment(tmp_path)
    try:
        _create_flow(
            fixture,
            account_id=fixture.account_ids[0],
            event_date=MID,
            amount="10.00",
            direction="contribution",
            kind="external_contribution",
            currency="USD",
        )
        _close(fixture)
        result = _bridge(fixture)
        assert not result.is_available
        assert result.value is None
        assert "not_computable_currency_conversion_incomplete" in result.reason_codes
        assert result.external_flow_summary.signed_total is None
    finally:
        _finish(fixture)


def test_missing_endpoint_valuation_is_null_and_fail_closed(tmp_path: Path) -> None:
    fixture = _environment(tmp_path)
    try:
        _close(fixture)
        result = _bridge(fixture, start_date=date(2030, 1, 30))
        assert not result.is_available
        assert result.opening_value is None
        assert result.closing_value is not None
        assert result.value is None
        assert "not_computable_opening_valuation_missing" in result.reason_codes
    finally:
        _finish(fixture)


def test_bridge_prerequisites_are_dedicated_and_do_not_use_top_level_union(
    tmp_path: Path,
) -> None:
    fixture = _environment(tmp_path, account_values=(("1000.00", "1100.00"),))
    try:
        _create_flow(
            fixture,
            account_id=fixture.account_ids[0],
            event_date=MID,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        _close(fixture)
        r08 = performance_availability_for_interval(
            fixture.session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.PORTFOLIO,
        )
        prerequisites = perf04a_bridge_prerequisites(
            fixture.session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.PORTFOLIO,
        )
        assert r08.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
        assert not r08.twrr.is_available
        assert prerequisites.is_available
        assert prerequisites.reason_codes == ()
    finally:
        _finish(fixture)
