"""Transaction-scoped representation helpers for S2a, not an import/Apply path.

The future reviewed S2b orchestrator owns source authority, overlap resolution,
preview fingerprints and the transaction. These helpers never commit or update
an existing economic fact. Keys identify canonical source facts across reports,
not document-local row offsets. No generic HTTP write surface exposes this mode.
"""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import InvestmentCashFlow, MyBrokerImport, PositionSnapshot
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.investment_cash_flows import (
    _coerce_flow_type,
    _require_account,
    _require_instrument,
    _validate_interest_is_not_deposit_duplicate,
)
from hermes_finance.services.positions import _normalize_quantity
from hermes_finance.services.positions import _require_instrument as _instrument

NATIVE_SOURCE = "broker_statement_native"
NET_BASIS = "broker_statement_net_v1"


def native_quantity_representable(session: Session, quantity: Decimal) -> bool:
    """Zero-write probe through the same Numeric bind/read processors as storage."""
    quantity_type = PositionSnapshot.__table__.c.quantity.type
    return session.scalar(select(literal(quantity, type_=quantity_type))) == quantity


def _amount(value: RubleAmount) -> int:
    if not isinstance(value, RubleAmount) or type(value.kopecks) is not int:
        raise TypeError("source money must be exact integer kopecks in RubleAmount")
    if not 0 <= value.kopecks <= 2**63 - 1:
        raise ValueError("source money outside nonnegative SQLite integer range")
    return value.kopecks


def _provenance(session: Session, import_id: int, row_key: str, day: date) -> None:
    if not isinstance(row_key, str) or re.fullmatch(r"[0-9a-f]{64}", row_key) is None:
        raise ValueError("source_row_key must be a canonical fact SHA256")
    evidence = session.get(MyBrokerImport, import_id, populate_existing=True)
    if evidence is None or not evidence.covered_from <= day <= evidence.covered_to:
        raise ValueError("source date must lie in the referenced accepted source interval")


def stage_native_position(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    quantity: Decimal | str | int,
    market_value: RubleAmount,
    price_date: date,
    source_import_id: int,
    source_row_key: str,
    asset_kind: str,
    bond_nkd_basis: str,
    accrued_interest: RubleAmount | None = None,
) -> PositionSnapshot:
    month = require_editable_reporting_month(session, reporting_month_id)
    if price_date != month.snapshot_date:
        raise ValueError("source price date must match the month snapshot date")
    account = _require_account(session, account_id)
    session.refresh(account)
    instrument = _instrument(session, instrument_id)
    if account.account_type not in {"brokerage", "iis"} or instrument.currency != "RUB":
        raise ValueError("native positions require a broker/IIS account and RUB instrument")
    kind = asset_kind
    if kind not in {"stock", "bond"} or kind != instrument.instrument_type:
        raise ValueError("native positions support stocks and bonds only")
    if bond_nkd_basis not in {"unknown", "included", "excluded", "not_applicable"}:
        raise ValueError("unsupported bond_nkd_basis")
    if (kind == "stock") != (bond_nkd_basis == "not_applicable"):
        raise ValueError("NKD basis must correspond to the source asset kind")
    _provenance(session, source_import_id, source_row_key, price_date)
    if not isinstance(quantity, (Decimal, str, int)) or isinstance(quantity, bool):
        raise TypeError("source quantity must be Decimal, decimal string or integer")
    normalized_quantity = _normalize_quantity(quantity, instrument_type=kind)
    if normalized_quantity > Decimal("999999999999.999999"):
        raise ValueError("source quantity outside Numeric(18,6) range")
    row = PositionSnapshot(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        historical_instrument_type=kind,
        quantity=normalized_quantity,
        market_value_kopecks=_amount(market_value),
        average_cost_per_unit_kopecks=None,
        market_price_per_unit_kopecks=None,
        cost_basis_kopecks=None,
        unrealized_result_kopecks=None,
        accrued_interest_kopecks=None if accrued_interest is None else _amount(accrued_interest),
        price_date=price_date,
        price_source=NATIVE_SOURCE,
        native_contract_version=1,
        source_import_id=source_import_id,
        source_row_key=source_row_key,
        bond_nkd_basis=bond_nkd_basis,
    )
    session.add(row)
    session.flush()
    session.refresh(row, attribute_names=["quantity"])
    if row.quantity != normalized_quantity:
        raise ValueError("source quantity cannot round-trip exactly in SQLite Numeric(18,6)")
    return row


def stage_native_payout(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: str,
    event_date: date,
    net_amount: RubleAmount,
    source_import_id: int,
    source_row_key: str,
) -> InvestmentCashFlow:
    month = require_editable_reporting_month(session, reporting_month_id)
    if not month.period_start <= event_date <= month.period_end:
        raise ValueError("payout must belong to the reporting month")
    account = _require_account(session, account_id)
    session.refresh(account)
    _require_instrument(session, instrument_id)
    instrument = _instrument(session, instrument_id)
    if account.account_type not in {"brokerage", "iis"} or instrument.currency != "RUB":
        raise ValueError("native payouts require a broker/IIS account and RUB instrument")
    if instrument.instrument_type not in {"stock", "bond"}:
        raise ValueError("native payouts support stocks and bonds only")
    if flow_type not in {"coupon", "dividend", "interest", "redemption"}:
        raise ValueError("net-only mode is limited to actual payouts")
    if (flow_type in {"coupon", "redemption"} and instrument.instrument_type != "bond") or (
        flow_type == "dividend" and instrument.instrument_type != "stock"
    ):
        raise ValueError("payout type conflicts with the source instrument kind")
    _validate_interest_is_not_deposit_duplicate(account, _coerce_flow_type(flow_type))
    _provenance(session, source_import_id, source_row_key, event_date)
    if (
        session.scalar(
            select(InvestmentCashFlow.id).where(
                InvestmentCashFlow.account_id == account_id,
                InvestmentCashFlow.source_row_key == source_row_key,
            )
        )
        is not None
    ):
        raise ValueError("canonical source cash fact already has a financial projection")
    row = InvestmentCashFlow(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        event_date=event_date,
        net_amount_kopecks=_amount(net_amount),
        gross_amount_kopecks=None,
        tax_amount_kopecks=None,
        commission_amount_kopecks=None,
        amount_basis=NET_BASIS,
        source_import_id=source_import_id,
        source_row_key=source_row_key,
        currency="RUB",
        source=NATIVE_SOURCE,
    )
    session.add(row)
    session.flush()
    return row
