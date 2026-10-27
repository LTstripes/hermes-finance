"""Disposable source-owned actual A and APP-only forecast B for terminal-lineage UI."""

from datetime import UTC, date, datetime

from sqlalchemy import select


def seed_terminal_payout(database):
    from test_statement_import_mybroker_endpoints import (
        _money_apply,
        _money_decide,
        money_batch_xml,
    )
    from test_statement_import_payout_reconciliation import forecast_month, move_payout_posted_date

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import (
        Instrument,
        InstrumentMarketMapping,
        InvestmentCashFlow,
        PositionSnapshot,
    )
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.applied_payouts import create_applied_payout
    from hermes_finance.services.broker_months import apply_broker_month, preview_broker_month
    from hermes_finance.services.reporting_months import create_reporting_month

    xml = move_payout_posted_date(money_batch_xml(coupons=("1000.00",)), "2030-01-31")
    xml = (
        xml.replace(b"1234567", b"7116700")
        .replace(b"31.12.2029", b"31.12.2037")
        .replace(b".01.2030", b".01.2038")
        .replace(b"2030-01-", b"2038-01-")
    )
    filename = "Брокерский 7116700 (01.01.38-31.01.38).xml"
    with database.session_factory() as session:
        account = create_account(
            session, name="Synthetic terminal payout", account_type="brokerage"
        )
        month = create_reporting_month(session, year=2038, month=1, snapshot_date=date(2038, 1, 31))
        scope = {"reporting_month_id": month.id, "account_id": account.id}
        kwargs = {**scope, "document": xml, "filename": filename, "optional_hashes": []}
        plan = preview_broker_month(session, **kwargs)
        assert plan["can_apply"], plan["blockers"]
        apply_broker_month(
            session,
            **kwargs,
            request_id="terminal-ui-base",
            confirmation_digest=plan["confirmation_digest"],
            reviewed_account_bindings=plan["account_bindings"],
        )
        instrument = session.scalar(select(Instrument).where(Instrument.isin == "RU000A000001"))
        money = MoneyIntent(
            contract_version="broker_money_v1", base_request_id="terminal-ui-base", **scope
        )
        originals = [(filename, xml)]
        _money_apply(
            session,
            _money_decide(session, money, originals, instrument.id),
            originals,
            "terminal-ui-money",
        )
        actual = session.scalar(
            select(InvestmentCashFlow).where(InvestmentCashFlow.account_id == account.id)
        )
        forecast = forecast_month(
            session, actual, year=2037, month=12, snapshot_date=date(2037, 12, 31)
        )
        position = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == forecast.reporting_month_id,
                PositionSnapshot.account_id == account.id,
                PositionSnapshot.instrument_id == instrument.id,
            )
        )
        mapping = session.get(InstrumentMarketMapping, instrument.id)
        app = create_applied_payout(
            session,
            reporting_month_id=forecast.reporting_month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            source_position_snapshot_id=position.id,
            provider=mapping.provider,
            provider_instrument_uid=mapping.provider_instrument_id,
            event_kind="coupon",
            identity_key="n:1",
            payment_date=date(2038, 2, 1),
            per_unit_amount="999.00",
            currency="RUB",
            fetched_at=datetime.now(UTC),
        )
        session.commit()
        return {
            "forecast_month_id": forecast.reporting_month_id,
            "intent": {
                **scope,
                "contract_version": "broker_payout_reconciliation_v1",
                "operation": "link",
                "base_request_id": "terminal-ui-base",
                "investment_cash_flow_id": actual.id,
                "applied_payout_id": app.id,
                "expected_cash_flow_id": None,
            },
        }
