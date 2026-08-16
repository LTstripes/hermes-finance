from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import FINANCIAL_ROUNDING, InstrumentType, PriceSource, RubleAmount
from hermes_finance.persistence import (
    Account,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.concurrency import ConcurrencyError
from hermes_finance.services.instruments import InstrumentNotFoundError


class PositionSnapshotNotFoundError(LookupError):
    pass


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _require_instrument(session: Session, instrument_id: int) -> Instrument:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")
    return instrument


def _normalize_quantity(quantity: int | Decimal | str, *, instrument_type: str) -> Decimal:
    if isinstance(quantity, bool):
        raise TypeError("quantity must be a number, not a bool")
    try:
        value = Decimal(quantity) if isinstance(quantity, str) else Decimal(quantity)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise TypeError("quantity must be an int, Decimal or decimal string") from error
    if not value.is_finite():
        raise ValueError("quantity must be finite")
    if value <= 0:
        raise ValueError("quantity must be positive")
    if value % Decimal("0.000001") != 0:
        raise ValueError("quantity must have at most 6 decimal places")
    if instrument_type == InstrumentType.STOCK.value and value % Decimal("1") != 0:
        raise ValueError("stock quantity must be a positive whole number")
    return value


def _normalize_per_unit_kopecks(value: RubleAmount | str | int, *, field: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        kopecks = value
    elif isinstance(value, str):
        kopecks = RubleAmount.from_api(value).kopecks
    elif isinstance(value, RubleAmount):
        kopecks = value.kopecks
    else:
        raise TypeError(f"{field} must be RubleAmount, decimal string or int kopecks")
    if kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return kopecks


def _coerce_price_source(price_source: PriceSource | str) -> PriceSource:
    try:
        return PriceSource(price_source)
    except ValueError as error:
        raise ValueError(f"unsupported price source: {price_source!r}") from error


def _reject_generic_t_invest_source(price_source: PriceSource) -> None:
    if price_source is PriceSource.T_INVEST:
        raise ValueError("t_invest price_source can only be set by quote apply")


def _compute_metrics(
    quantity: Decimal,
    average_cost_per_unit_kopecks: int,
    market_price_per_unit_kopecks: int,
    accrued_interest_kopecks: int | None,
) -> tuple[int, int, int]:
    market_value = (
        quantity * Decimal(market_price_per_unit_kopecks) + Decimal(accrued_interest_kopecks or 0)
    ).to_integral_value(rounding=FINANCIAL_ROUNDING)
    cost_basis = (quantity * Decimal(average_cost_per_unit_kopecks)).to_integral_value(
        rounding=FINANCIAL_ROUNDING
    )
    unrealized_result = market_value - cost_basis
    return int(market_value), int(cost_basis), int(unrealized_result)


def list_position_snapshots(session: Session) -> list[PositionSnapshot]:
    return list(
        session.scalars(
            select(PositionSnapshot).order_by(
                PositionSnapshot.reporting_month_id,
                PositionSnapshot.account_id,
                PositionSnapshot.instrument_id,
                PositionSnapshot.id,
            )
        )
    )


def get_position_snapshot(session: Session, snapshot_id: int) -> PositionSnapshot:
    snapshot = session.get(PositionSnapshot, snapshot_id)
    if snapshot is None:
        raise PositionSnapshotNotFoundError(f"position snapshot {snapshot_id} was not found")
    return snapshot


def get_position_snapshot_by_key(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
) -> PositionSnapshot | None:
    """Return the snapshot for ``(month, account, instrument)`` or ``None``.

    Read-only lookup used by the API layer to map duplicate-snapshot
    creation attempts to an HTTP 409 conflict without changing the
    ValueError contract of :func:`create_position_snapshot`.
    """
    return session.scalar(
        select(PositionSnapshot).where(
            PositionSnapshot.reporting_month_id == reporting_month_id,
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.instrument_id == instrument_id,
        )
    )


def create_position_snapshot(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    quantity: int | Decimal | str,
    average_cost_per_unit: RubleAmount | str | int,
    market_price_per_unit: RubleAmount | str | int,
    accrued_interest: RubleAmount | str | int | None = None,
    price_date: date,
    price_source: PriceSource | str = PriceSource.MANUAL,
    manual_adjustment: bool = False,
    notes: str | None = None,
) -> PositionSnapshot:
    require_editable_reporting_month(session, reporting_month_id)
    _require_account(session, account_id)
    instrument = _require_instrument(session, instrument_id)
    quantity = _normalize_quantity(quantity, instrument_type=instrument.instrument_type)
    average_cost = _normalize_per_unit_kopecks(average_cost_per_unit, field="average_cost_per_unit")
    market_price = _normalize_per_unit_kopecks(market_price_per_unit, field="market_price_per_unit")
    accrued = (
        _normalize_per_unit_kopecks(accrued_interest, field="accrued_interest")
        if accrued_interest is not None
        else None
    )
    source = _coerce_price_source(price_source)
    _reject_generic_t_invest_source(source)
    market_value, cost_basis, unrealized = _compute_metrics(
        quantity, average_cost, market_price, accrued
    )
    snapshot = PositionSnapshot(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        average_cost_per_unit_kopecks=average_cost,
        market_price_per_unit_kopecks=market_price,
        accrued_interest_kopecks=accrued,
        market_value_kopecks=market_value,
        cost_basis_kopecks=cost_basis,
        unrealized_result_kopecks=unrealized,
        price_date=price_date,
        price_source=source.value,
        manual_adjustment=manual_adjustment,
        notes=notes,
    )
    session.add(snapshot)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError(
            "position snapshot already exists for month, account and instrument"
        ) from error
    session.refresh(snapshot)
    return snapshot


def update_position_snapshot(
    session: Session,
    snapshot_id: int,
    *,
    quantity: int | Decimal | str | None = None,
    average_cost_per_unit: RubleAmount | str | int | None = None,
    market_price_per_unit: RubleAmount | str | int | None = None,
    accrued_interest: RubleAmount | str | int | None = None,
    price_date: date | None = None,
    price_source: PriceSource | str | None = None,
    manual_adjustment: bool | None = None,
    notes: str | None = None,
    expected_updated_at: datetime | None = None,
) -> PositionSnapshot:
    snapshot = get_position_snapshot(session, snapshot_id)
    require_editable_child_month(session, snapshot)
    instrument = _require_instrument(session, snapshot.instrument_id)
    if expected_updated_at is not None and snapshot.updated_at != expected_updated_at:
        raise ConcurrencyError("updated_at", expected_updated_at, snapshot.updated_at)
    current_source = _coerce_price_source(snapshot.price_source)
    requested_source = (
        _coerce_price_source(price_source) if price_source is not None else current_source
    )
    next_price = snapshot.market_price_per_unit_kopecks
    if market_price_per_unit is not None:
        next_price = _normalize_per_unit_kopecks(
            market_price_per_unit, field="market_price_per_unit"
        )
    next_date = price_date if price_date is not None else snapshot.price_date
    quote_changed = (
        next_price != snapshot.market_price_per_unit_kopecks or next_date != snapshot.price_date
    )
    if requested_source is PriceSource.T_INVEST:
        if current_source is not PriceSource.T_INVEST:
            _reject_generic_t_invest_source(requested_source)
        if quote_changed:
            raise ValueError("cannot change a T-Invest quote while keeping t_invest price_source")
    if quantity is not None:
        snapshot.quantity = _normalize_quantity(
            quantity, instrument_type=instrument.instrument_type
        )
    if average_cost_per_unit is not None:
        snapshot.average_cost_per_unit_kopecks = _normalize_per_unit_kopecks(
            average_cost_per_unit, field="average_cost_per_unit"
        )
    if market_price_per_unit is not None:
        snapshot.market_price_per_unit_kopecks = next_price
    if accrued_interest is not None:
        snapshot.accrued_interest_kopecks = _normalize_per_unit_kopecks(
            accrued_interest, field="accrued_interest"
        )
    if price_date is not None:
        snapshot.price_date = next_date
    if price_source is not None:
        snapshot.price_source = requested_source.value
    if manual_adjustment is not None:
        snapshot.manual_adjustment = manual_adjustment
    if notes is not None:
        snapshot.notes = notes

    (
        snapshot.market_value_kopecks,
        snapshot.cost_basis_kopecks,
        snapshot.unrealized_result_kopecks,
    ) = _compute_metrics(
        snapshot.quantity,
        snapshot.average_cost_per_unit_kopecks,
        snapshot.market_price_per_unit_kopecks,
        snapshot.accrued_interest_kopecks,
    )
    session.commit()
    session.refresh(snapshot)
    return snapshot


def apply_snapshot_market_quote(
    session: Session,
    snapshot: PositionSnapshot,
    *,
    market_price_per_unit_kopecks: int,
    price_date: date,
    price_source: PriceSource,
) -> PositionSnapshot:
    """Stage a backend-authoritative quote on a snapshot without committing.

    Accrued interest (NKD) is left unchanged. The caller owns the transaction.
    """
    require_editable_child_month(session, snapshot)
    if market_price_per_unit_kopecks < 0:
        raise ValueError("market_price_per_unit must not be negative")
    snapshot.market_price_per_unit_kopecks = market_price_per_unit_kopecks
    snapshot.price_date = price_date
    snapshot.price_source = _coerce_price_source(price_source).value
    snapshot.manual_adjustment = False
    (
        snapshot.market_value_kopecks,
        snapshot.cost_basis_kopecks,
        snapshot.unrealized_result_kopecks,
    ) = _compute_metrics(
        snapshot.quantity,
        snapshot.average_cost_per_unit_kopecks,
        snapshot.market_price_per_unit_kopecks,
        snapshot.accrued_interest_kopecks,
    )
    session.flush()
    return snapshot


def delete_position_snapshot(session: Session, snapshot_id: int) -> None:
    snapshot = get_position_snapshot(session, snapshot_id)
    require_editable_child_month(session, snapshot)
    session.delete(snapshot)
    session.commit()
