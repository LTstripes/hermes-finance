"""Independent synthetic vectors and fail-closed regressions for R08-03."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    TwrrAvailabilityStatus,
    TwrrBoundary,
    TwrrQuality,
    TwrrReasonCode,
    calculate_twrr,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import AccountPerformanceScopeMembership, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.portfolio_twrr import portfolio_twrr_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month
from hermes_finance.services.valuation_boundaries import (
    create_external_flow_boundary_group,
    create_observed_valuation_point,
)

START = date(2030, 1, 31)
FIRST_FLOW_DATE = date(2030, 2, 10)
SECOND_FLOW_DATE = date(2030, 2, 20)
END = date(2030, 2, 28)


def _environment(
    tmp_path: Path,
    *,
    closing_value: str = "1333.50",
) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-03-twrr.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    account = create_account(
        session, name="Synthetic TWRR Account", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic TWRR Instrument", instrument_type="bond"
    )
    for month, value in ((january, "1000.00"), (february, closing_value)):
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit=value,
            market_price_per_unit=value,
            price_date=month.snapshot_date,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic TWRR Deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic TWRR Cash",
            amount="0.00",
        )
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()
    return session, database, january.id, february.id, account.id


def _close_interval(session: Session, january_id: int, february_id: int) -> None:
    close_reporting_month(session, january_id)
    close_reporting_month(session, february_id)


def _flow(
    session: Session,
    month_id: int,
    account_id: int,
    *,
    event_date: date,
    amount: str,
    direction: str,
    kind: str,
):
    return create_external_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        event_date=event_date,
        boundary_amount=amount,
        direction=direction,
        kind=kind,
        scope_membership="stable_in_scope",
    )


def test_calculate_twrr_matches_independent_two_flow_reference_vector() -> None:
    result = calculate_twrr(
        100_000,
        133_350,
        (
            TwrrBoundary(FIRST_FLOW_DATE, 10_000, 110_000, 120_000),
            TwrrBoundary(SECOND_FLOW_DATE, -5_000, 132_000, 127_000),
        ),
    )

    assert result.availability is TwrrAvailabilityStatus.AVAILABLE
    assert result.quality is TwrrQuality.EXACT
    assert result.return_rate == Decimal("0.2705")


def test_portfolio_twrr_chains_explicit_persisted_boundaries(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        first = _flow(
            session,
            february_id,
            account_id,
            event_date=FIRST_FLOW_DATE,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        second = _flow(
            session,
            february_id,
            account_id,
            event_date=SECOND_FLOW_DATE,
            amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
        )
        for flow, pre, post in ((first, "1100.00", "1200.00"), (second, "1320.00", "1270.00")):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="portfolio",
                observed_date=flow.event_date,
                total_value=pre,
                performance_currency="RUB",
                provenance_kind="synthetic_twrr_vector",
                relation="pre_external_flow",
                external_flow_id=flow.id,
            )
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="portfolio",
                observed_date=flow.event_date,
                total_value=post,
                performance_currency="RUB",
                provenance_kind="synthetic_twrr_vector",
                relation="post_external_flow",
                external_flow_id=flow.id,
            )
        _close_interval(session, january_id, february_id)

        result = portfolio_twrr_for_interval(session, start_date=START, end_date=END)

        assert result.availability is TwrrAvailabilityStatus.AVAILABLE
        assert result.quality is TwrrQuality.EXACT
        assert result.value == Decimal("27.05")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_twrr_is_flat_or_negative_without_flow(tmp_path: Path) -> None:
    session, database, january_id, february_id, _ = _environment(tmp_path, closing_value="900.00")
    try:
        _close_interval(session, january_id, february_id)
        result = portfolio_twrr_for_interval(session, start_date=START, end_date=END)

        assert result.availability is TwrrAvailabilityStatus.AVAILABLE
        assert result.value == Decimal("-10")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_twrr_flat_period_is_exact_zero(tmp_path: Path) -> None:
    session, database, january_id, february_id, _ = _environment(tmp_path, closing_value="1000.00")
    try:
        _close_interval(session, january_id, february_id)
        result = portfolio_twrr_for_interval(session, start_date=START, end_date=END)

        assert result.availability is TwrrAvailabilityStatus.AVAILABLE
        assert result.quality is TwrrQuality.EXACT
        assert result.value == Decimal("0")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_twrr_group_plus_standalone_same_day_fails_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        grouped = _flow(
            session,
            february_id,
            account_id,
            event_date=FIRST_FLOW_DATE,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        standalone = _flow(
            session,
            february_id,
            account_id,
            event_date=FIRST_FLOW_DATE,
            amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
        )
        group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FIRST_FLOW_DATE,
            flow_ids=[grouped.id],
            scope="portfolio",
        )
        for relation, value, boundary_kwargs in (
            ("pre_external_flow", "1100.00", {"boundary_group_id": group.id}),
            ("post_external_flow", "1200.00", {"boundary_group_id": group.id}),
            ("pre_external_flow", "1200.00", {"external_flow_id": standalone.id}),
            ("post_external_flow", "1150.00", {"external_flow_id": standalone.id}),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="portfolio",
                observed_date=FIRST_FLOW_DATE,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic_same_day_order_regression",
                relation=relation,
                **boundary_kwargs,
            )
        _close_interval(session, january_id, february_id)

        result = portfolio_twrr_for_interval(session, start_date=START, end_date=END)

        assert result.availability is TwrrAvailabilityStatus.NOT_COMPUTABLE
        assert result.quality is TwrrQuality.UNAVAILABLE
        assert result.value is None
        assert result.reason_codes == ("not_computable_valuation_boundary_order_unknown",)
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_twrr_missing_one_boundary_fails_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(
            session,
            february_id,
            account_id,
            event_date=FIRST_FLOW_DATE,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="portfolio",
            observed_date=FIRST_FLOW_DATE,
            total_value="1100.00",
            performance_currency="RUB",
            provenance_kind="synthetic_missing_post",
            relation="pre_external_flow",
            external_flow_id=flow.id,
        )
        _close_interval(session, january_id, february_id)
        result = portfolio_twrr_for_interval(session, start_date=START, end_date=END)

        assert result.availability is TwrrAvailabilityStatus.NOT_COMPUTABLE
        assert result.quality is TwrrQuality.UNAVAILABLE
        assert result.value is None
        assert result.reason_codes == ("not_computable_valuation_boundary_missing",)
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_twrr_zero_denominator_fails_closed() -> None:
    result = calculate_twrr(0, 100, ())

    assert result.availability is TwrrAvailabilityStatus.NOT_COMPUTABLE
    assert result.reason_codes == (TwrrReasonCode.ZERO_OR_NEGATIVE_DENOMINATOR.value,)


def test_portfolio_twrr_api_returns_period_value_without_annualizing(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(
            session,
            february_id,
            account_id,
            event_date=FIRST_FLOW_DATE,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        for relation, value in (
            ("pre_external_flow", "1100.00"),
            ("post_external_flow", "1200.00"),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="portfolio",
                observed_date=FIRST_FLOW_DATE,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic_twrr_api",
                relation=relation,
                external_flow_id=flow.id,
            )
        _close_interval(session, january_id, february_id)
        session.close()

        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/twrr",
                params={"start_date": START.isoformat(), "end_date": END.isoformat()},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["metric"] == "twrr"
        assert body["value_unit"] == "percentage_points"
        assert body["annualized"] is False
        assert body["value"] == "22.2375"
        assert body["quality"] == "exact"
    finally:
        database.engine.dispose()
