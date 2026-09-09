"""PERF-H3 tax, fee and direct-payout performance-boundary regressions."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from test_r08_01c_performance_availability import END, START, _close_two_months, _environment

from hermes_finance.persistence import (
    AppliedProviderPayout,
    ExpectedCashFlow,
    Instrument,
    InvestmentCashFlow,
    PositionSnapshot,
)
from hermes_finance.services.cash_boundary_coverage import attest_cash_boundary_history
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.portfolio_xirr import _cash_flows_from_availability

MID = date(2030, 2, 15)


def _availability(session, january_id: int, february_id: int, account_id: int):
    _close_two_months(session, january_id, february_id)
    return performance_availability_for_interval(
        session,
        start_date=START,
        end_date=END,
        scope="account",
        account_id=account_id,
    )


def _external_withdrawal(session, february_id: int, account_id: int, amount: str):
    flow = create_external_flow(
        session,
        reporting_month_id=february_id,
        account_id=account_id,
        event_date=MID,
        boundary_amount=amount,
        direction="withdrawal",
        kind="external_withdrawal",
        scope_membership="stable_in_scope",
    )
    attest_cash_boundary_history(session, account_id=account_id, covered_from=START, covered_to=END)
    return flow


def _investment_flow(
    session,
    february_id: int,
    account_id: int,
    instrument_id: int | None,
    *,
    flow_type: str,
    gross: str,
    tax: str = "0.00",
    commission: str = "0.00",
    net: str,
):
    return create_investment_cash_flow(
        session,
        reporting_month_id=february_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        event_date=MID,
        gross_amount=gross,
        tax_amount=tax,
        commission_amount=commission,
        net_amount=net,
        source="synthetic-accepted-evidence",
    )


def test_embedded_withholding_reconciles_to_actual_external_boundary(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        legacy = _investment_flow(
            session,
            february_id,
            account_id,
            None,
            flow_type="withdrawal",
            gross="10000.00",
            tax="1300.00",
            net="8700.00",
        )
        boundary = _external_withdrawal(session, february_id, account_id, "8700.00")

        result = _availability(session, january_id, february_id, account_id)

        assert result.xirr.is_available
        assert result.external_flows.legacy_unclassified_flow_ids == ()
        assert [
            (flow.id, flow.boundary_amount_kopecks) for flow in result.external_flows.flows
        ] == [(boundary.id, 870_000)]
        assert legacy.id not in result.external_flows.legacy_unclassified_flow_ids
    finally:
        session.close()
        database.engine.dispose()


def test_unrelated_same_day_tax_and_commission_do_not_reconcile_withdrawal(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        legacy = _investment_flow(
            session,
            february_id,
            account_id,
            None,
            flow_type="withdrawal",
            gross="10000.00",
            net="10000.00",
        )
        tax = _investment_flow(
            session,
            february_id,
            account_id,
            None,
            flow_type="tax",
            gross="0.00",
            tax="1300.00",
            net="-1300.00",
        )
        commission = _investment_flow(
            session,
            february_id,
            account_id,
            None,
            flow_type="commission",
            gross="0.00",
            commission="200.00",
            net="-200.00",
        )
        boundary = _external_withdrawal(session, february_id, account_id, "8500.00")

        result = _availability(session, january_id, february_id, account_id)

        assert not result.xirr.is_available
        assert result.external_flows.legacy_unclassified_flow_ids == (legacy.id,)
        assert [flow.boundary_amount_kopecks for flow in result.external_flows.flows] == [
            boundary.boundary_amount_kopecks
        ]
        assert tax.net_amount_kopecks == -130_000
        assert commission.net_amount_kopecks == -20_000
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_mismatched_gross_net_does_not_guess_legacy_withdrawal_boundary(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        legacy = _investment_flow(
            session,
            february_id,
            account_id,
            None,
            flow_type="withdrawal",
            gross="10000.00",
            tax="1300.00",
            net="8700.00",
        )
        _external_withdrawal(session, february_id, account_id, "10000.00")

        result = _availability(session, january_id, february_id, account_id)

        assert not result.xirr.is_available
        assert result.external_flows.legacy_unclassified_flow_ids == (legacy.id,)
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_standalone_internal_tax_is_a_cost_not_an_external_flow(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        tax = _investment_flow(
            session,
            february_id,
            account_id,
            None,
            flow_type="tax",
            gross="0.00",
            tax="1300.00",
            net="-1300.00",
        )

        result = _availability(session, january_id, february_id, account_id)

        assert result.xirr.is_available
        assert result.external_flows.flows == ()
        assert result.external_flows.legacy_unclassified_flow_ids == ()
        assert tax.net_amount_kopecks == -130_000
    finally:
        session.close()
        database.engine.dispose()


def test_retained_dividend_is_income_evidence_without_external_flow(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        _investment_flow(
            session,
            february_id,
            account_id,
            instrument.id,
            flow_type="dividend",
            gross="10000.00",
            tax="1300.00",
            net="8700.00",
        )

        result = _availability(session, january_id, february_id, account_id)

        assert result.xirr.is_available
        assert result.external_flows.flows == ()
    finally:
        session.close()
        database.engine.dispose()


def test_dividend_then_owner_withdrawal_enters_xirr_once_at_boundary_amount(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        _investment_flow(
            session,
            february_id,
            account_id,
            instrument.id,
            flow_type="dividend",
            gross="10000.00",
            tax="1300.00",
            net="8700.00",
        )
        boundary = _external_withdrawal(session, february_id, account_id, "8700.00")

        result = _availability(session, january_id, february_id, account_id)
        cash_flows = _cash_flows_from_availability(result)

        assert result.xirr.is_available
        assert [flow.id for flow in result.external_flows.flows] == [boundary.id]
        assert [flow.amount_kopecks for flow in cash_flows] == [
            -340_000,
            870_000,
            340_000,
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_direct_dividend_uses_owner_receipt_not_gross_or_internal_tax(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        _investment_flow(
            session,
            february_id,
            account_id,
            instrument.id,
            flow_type="dividend",
            gross="10000.00",
            tax="1300.00",
            net="8700.00",
        )
        boundary = _external_withdrawal(session, february_id, account_id, "8700.00")

        result = _availability(session, january_id, february_id, account_id)
        cash_flows = _cash_flows_from_availability(result)
        tax_rows = list(
            session.scalars(select(InvestmentCashFlow).where(InvestmentCashFlow.flow_type == "tax"))
        )

        assert result.xirr.is_available
        assert [flow.id for flow in result.external_flows.flows] == [boundary.id]
        assert [flow.amount_kopecks for flow in cash_flows] == [-340_000, 870_000, 340_000]
        assert tax_rows == []
    finally:
        session.close()
        database.engine.dispose()


def test_ambiguous_direct_payout_holding_provenance_fails_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        first = session.scalar(select(Instrument))
        assert first is not None
        second = create_instrument(
            session,
            name="Synthetic second dividend holding",
            instrument_type="stock",
        )
        for instrument_id in (first.id, second.id):
            _investment_flow(
                session,
                february_id,
                account_id,
                instrument_id,
                flow_type="dividend",
                gross="10000.00",
                tax="1300.00",
                net="8700.00",
            )
        _external_withdrawal(session, february_id, account_id, "8700.00")

        result = _availability(session, january_id, february_id, account_id)

        assert not result.xirr.is_available
        assert result.external_flows.legacy_unclassified_flow_ids == ()
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_expected_payout_without_actual_evidence_is_not_a_realised_flow(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        session.add(
            ExpectedCashFlow(
                reporting_month_id=february_id,
                account_id=account_id,
                instrument_id=instrument.id,
                flow_type="dividend",
                expected_date=MID,
                gross_amount_kopecks=1_000_000,
                expected_tax_amount_kopecks=130_000,
                expected_net_amount_kopecks=870_000,
                currency="RUB",
                source="synthetic-calendar",
                source_as_of_date=START,
                forecast_version="h3",
                is_confirmed=True,
                is_approximate=False,
            )
        )
        session.commit()

        result = _availability(session, january_id, february_id, account_id)

        assert result.external_flows.flows == ()
        assert not result.xirr.is_available
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_provider_payout_without_actual_evidence_is_not_a_realised_flow(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        snapshot = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == february_id,
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.instrument_id == instrument.id,
            )
        )
        assert snapshot is not None
        session.add(
            AppliedProviderPayout(
                reporting_month_id=february_id,
                account_id=account_id,
                instrument_id=instrument.id,
                source_position_snapshot_id=snapshot.id,
                provider="synthetic-calendar",
                provider_instrument_uid="SYN-H3-DIVIDEND",
                event_kind="dividend",
                identity_key="synthetic-h3-payment",
                lifecycle="active",
                payment_date=MID,
                quantity=Decimal("1"),
                per_unit_amount="10000.00",
                total_amount_kopecks=1_000_000,
                currency="RUB",
                amount_basis="provider_announced",
                is_approximate=True,
                provider_status="expected",
                first_applied_at=datetime(2030, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        result = _availability(session, january_id, february_id, account_id)

        assert result.external_flows.flows == ()
        assert not result.xirr.is_available
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_valid_direct_payout_keeps_xirr_but_requires_twrr_observed_boundaries(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        instrument = session.scalar(select(Instrument))
        assert instrument is not None
        _investment_flow(
            session,
            february_id,
            account_id,
            instrument.id,
            flow_type="dividend",
            gross="10000.00",
            tax="1300.00",
            net="8700.00",
        )
        _external_withdrawal(session, february_id, account_id, "8700.00")

        result = _availability(session, january_id, february_id, account_id)

        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_missing",)
    finally:
        session.close()
        database.engine.dispose()
