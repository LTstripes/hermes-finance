"""Loopback-only synthetic browser fixture; never resolves a real provider or DB."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import mkdtemp

from sqlalchemy import select
from t_invest_mapping_fixtures import accept_t_invest_mapping
from test_payout_api import RecordingPayoutProvider, build_environment

from hermes_finance.database import create_database
from hermes_finance.domain import ExpectedCashFlowType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchResult
from hermes_finance.persistence import Base, Instrument
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month


def create_browser_app():
    directory = Path(mkdtemp(prefix="hermes-payout-synthetic-"))
    database = create_database(directory / "synthetic.db")
    Base.metadata.create_all(database.engine)
    second_uid = "55555555-5555-5555-5555-555555555555"
    empty_uid = "66666666-6666-6666-6666-666666666666"
    with database.session_factory() as session:
        month_id, account_id, _, _ = build_environment(session)
        for name, uid in [
            ("Synthetic duplicate and principal", second_uid),
            ("Synthetic unmapped", None),
            ("Synthetic no events", empty_uid),
        ]:
            instrument = create_instrument(session, name=name, instrument_type=InstrumentType.BOND)
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument.id,
                quantity="2.000000",
                average_cost_per_unit="100.00",
                market_price_per_unit="101.00",
                price_date=date(2030, 5, 12),
            )
            if uid:
                accept_t_invest_mapping(session, instrument.id, uid, kind=InstrumentType.BOND)
            if uid == second_uid:
                create_expected_cash_flow(
                    session,
                    reporting_month_id=month_id,
                    account_id=account_id,
                    instrument_id=instrument.id,
                    flow_type=ExpectedCashFlowType.COUPON,
                    expected_date=date(2030, 6, 15),
                    gross_amount="999.00",
                    expected_net_amount="999.00",
                    source="synthetic",
                    source_as_of_date=date(2030, 5, 12),
                    forecast_version="v1",
                    is_confirmed=False,
                )
        for year in range(2031, 2037):
            extra_month = create_reporting_month(
                session, year=year, month=5, snapshot_date=date(year, 5, 12)
            )
            for instrument in session.scalars(select(Instrument).order_by(Instrument.id)):
                create_position_snapshot(
                    session,
                    reporting_month_id=extra_month.id,
                    account_id=account_id,
                    instrument_id=instrument.id,
                    quantity="2.000000",
                    average_cost_per_unit="100.00",
                    market_price_per_unit="101.00",
                    price_date=date(year, 5, 12),
                )
                if instrument.name == "Synthetic duplicate and principal":
                    create_expected_cash_flow(
                        session,
                        reporting_month_id=extra_month.id,
                        account_id=account_id,
                        instrument_id=instrument.id,
                        flow_type=ExpectedCashFlowType.COUPON,
                        expected_date=date(year, 6, 15),
                        gross_amount="999.00",
                        expected_net_amount="999.00",
                        source="synthetic",
                        source_as_of_date=date(year, 5, 12),
                        forecast_version="v1",
                        is_confirmed=False,
                    )

    class SyntheticProvider(RecordingPayoutProvider):
        def fetch_payouts(self, request):
            result = super().fetch_payouts(request)
            year = request.calendar_from.year
            attempt = sum(
                saved.instrument_uid == request.instrument_uid and saved.calendar_from.year == year
                for saved in self.requests
            )
            if year == 2033 and request.instrument_uid == second_uid and attempt >= 2:
                raise RuntimeError("synthetic provider failure")
            revised = year == 2032 and attempt >= 3
            payment = date(year, 6, 16 if revised else 15)
            result = replace(
                result,
                events=tuple(
                    replace(
                        event,
                        payment_date=payment,
                        provider_filter_date=payment,
                        per_unit_amount=Decimal("30.00") if revised else event.per_unit_amount,
                    )
                    for event in result.events
                ),
            )
            if request.instrument_uid == empty_uid:
                return PayoutFetchResult(
                    provider=result.provider, instrument_uid=request.instrument_uid, events=()
                )
            if request.instrument_uid != second_uid:
                return result
            principal = PayoutEvent(
                provider="t_invest",
                instrument_uid=second_uid,
                event_kind=PayoutEventKind.REDEMPTION,
                identity_key="synthetic-principal",
                status=PayoutEventStatus.OK,
                payment_date=date(request.calendar_from.year, 7, 15),
                per_unit_amount=Decimal("100.00"),
                currency="RUB",
                source_method="GetBondEvents",
                provider_filter_basis="event_date",
                provider_filter_date=date(request.calendar_from.year, 7, 15),
            )
            return PayoutFetchResult(
                provider=result.provider,
                instrument_uid=request.instrument_uid,
                events=(*result.events, principal),
            )

    return create_app(
        database,
        static_dir=Path(__file__).resolve().parents[2] / "frontend" / "dist",
        payout_provider=SyntheticProvider(),
    )
