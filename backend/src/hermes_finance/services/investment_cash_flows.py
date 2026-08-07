from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import InvestmentCashFlowType, RubleAmount
from hermes_finance.persistence import Account, Instrument, InvestmentCashFlow
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.instruments import InstrumentNotFoundError


class InvestmentCashFlowNotFoundError(LookupError):
    pass


def _require_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def _require_instrument(session: Session, instrument_id: int | None) -> None:
    if instrument_id is not None and session.get(Instrument, instrument_id) is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if not normalized:
        raise ValueError("currency must not be empty")
    return normalized


def _normalize_nonnegative_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _normalize_net_amount(amount: RubleAmount | str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError("net_amount must be RubleAmount or decimal string")
    return amount.kopecks


def _coerce_flow_type(flow_type: InvestmentCashFlowType | str) -> InvestmentCashFlowType:
    try:
        return InvestmentCashFlowType(flow_type)
    except ValueError as error:
        raise ValueError(f"unsupported investment cash flow type: {flow_type!r}") from error


def _validate_net(
    *,
    gross_amount_kopecks: int,
    tax_amount_kopecks: int,
    commission_amount_kopecks: int,
    net_amount_kopecks: int,
) -> None:
    expected = gross_amount_kopecks - tax_amount_kopecks - commission_amount_kopecks
    if net_amount_kopecks != expected:
        raise ValueError(
            "net_amount must equal gross_amount minus tax_amount and commission_amount"
        )


def _validate_interest_is_not_deposit_duplicate(
    account: Account, flow_type: InvestmentCashFlowType
) -> None:
    if flow_type is InvestmentCashFlowType.INTEREST and account.account_type in {
        "deposit",
        "savings",
    }:
        raise ValueError(
            "deposit and savings interest must be recorded in deposit_snapshots.actual_interest_received"
        )


def list_investment_cash_flows(session: Session) -> list[InvestmentCashFlow]:
    return list(
        session.scalars(
            select(InvestmentCashFlow).order_by(
                InvestmentCashFlow.reporting_month_id,
                InvestmentCashFlow.event_date,
                InvestmentCashFlow.id,
            )
        )
    )


def list_passive_income_cash_flows(
    session: Session, reporting_month_id: int
) -> list[InvestmentCashFlow]:
    types = [
        flow_type.value
        for flow_type in InvestmentCashFlowType
        if flow_type.counts_as_passive_income
    ]
    return list(
        session.scalars(
            select(InvestmentCashFlow)
            .where(
                InvestmentCashFlow.reporting_month_id == reporting_month_id,
                InvestmentCashFlow.flow_type.in_(types),
            )
            .order_by(InvestmentCashFlow.event_date, InvestmentCashFlow.id)
        )
    )


def get_investment_cash_flow(session: Session, flow_id: int) -> InvestmentCashFlow:
    flow = session.get(InvestmentCashFlow, flow_id)
    if flow is None:
        raise InvestmentCashFlowNotFoundError(f"investment cash flow {flow_id} was not found")
    return flow


def create_investment_cash_flow(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    flow_type: InvestmentCashFlowType | str,
    event_date: date,
    gross_amount: RubleAmount | str,
    tax_amount: RubleAmount | str = "0.00",
    commission_amount: RubleAmount | str = "0.00",
    net_amount: RubleAmount | str,
    instrument_id: int | None = None,
    currency: str = "RUB",
    source: str,
    notes: str | None = None,
) -> InvestmentCashFlow:
    require_editable_reporting_month(session, reporting_month_id)
    account = _require_account(session, account_id)
    _require_instrument(session, instrument_id)
    normalized_type = _coerce_flow_type(flow_type)
    _validate_interest_is_not_deposit_duplicate(account, normalized_type)
    gross = _normalize_nonnegative_amount(gross_amount, field="gross_amount")
    tax = _normalize_nonnegative_amount(tax_amount, field="tax_amount")
    commission = _normalize_nonnegative_amount(commission_amount, field="commission_amount")
    net = _normalize_net_amount(net_amount)
    _validate_net(
        gross_amount_kopecks=gross,
        tax_amount_kopecks=tax,
        commission_amount_kopecks=commission,
        net_amount_kopecks=net,
    )
    flow = InvestmentCashFlow(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=normalized_type.value,
        event_date=event_date,
        gross_amount_kopecks=gross,
        tax_amount_kopecks=tax,
        commission_amount_kopecks=commission,
        net_amount_kopecks=net,
        currency=_normalize_currency(currency),
        source=_normalize_text(source, field="source"),
        notes=notes,
    )
    session.add(flow)
    session.commit()
    session.refresh(flow)
    return flow


def update_investment_cash_flow(
    session: Session,
    flow_id: int,
    *,
    flow_type: InvestmentCashFlowType | str | None = None,
    event_date: date | None = None,
    gross_amount: RubleAmount | str | None = None,
    tax_amount: RubleAmount | str | None = None,
    commission_amount: RubleAmount | str | None = None,
    net_amount: RubleAmount | str | None = None,
    instrument_id: int | None = None,
    currency: str | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> InvestmentCashFlow:
    flow = get_investment_cash_flow(session, flow_id)
    require_editable_child_month(session, flow)
    account = _require_account(session, flow.account_id)
    if flow_type is not None:
        flow.flow_type = _coerce_flow_type(flow_type).value
    _validate_interest_is_not_deposit_duplicate(account, InvestmentCashFlowType(flow.flow_type))
    if event_date is not None:
        flow.event_date = event_date
    if gross_amount is not None:
        flow.gross_amount_kopecks = _normalize_nonnegative_amount(
            gross_amount, field="gross_amount"
        )
    if tax_amount is not None:
        flow.tax_amount_kopecks = _normalize_nonnegative_amount(tax_amount, field="tax_amount")
    if commission_amount is not None:
        flow.commission_amount_kopecks = _normalize_nonnegative_amount(
            commission_amount, field="commission_amount"
        )
    if net_amount is not None:
        flow.net_amount_kopecks = _normalize_net_amount(net_amount)
    if instrument_id is not None:
        _require_instrument(session, instrument_id)
        flow.instrument_id = instrument_id
    if currency is not None:
        flow.currency = _normalize_currency(currency)
    if source is not None:
        flow.source = _normalize_text(source, field="source")
    if notes is not None:
        flow.notes = notes
    _validate_net(
        gross_amount_kopecks=flow.gross_amount_kopecks,
        tax_amount_kopecks=flow.tax_amount_kopecks,
        commission_amount_kopecks=flow.commission_amount_kopecks,
        net_amount_kopecks=flow.net_amount_kopecks,
    )
    session.commit()
    session.refresh(flow)
    return flow


def delete_investment_cash_flow(session: Session, flow_id: int) -> None:
    flow = get_investment_cash_flow(session, flow_id)
    require_editable_child_month(session, flow)
    session.delete(flow)
    session.commit()
