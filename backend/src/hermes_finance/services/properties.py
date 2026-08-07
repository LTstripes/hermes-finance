from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain import FINANCIAL_ROUNDING, RubleAmount
from hermes_finance.persistence import PropertySnapshot
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)


class PropertySnapshotNotFoundError(LookupError):
    pass


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _sum_field(session: Session, month_id: int, field) -> int:
    total = session.scalar(
        select(func.coalesce(func.sum(field), 0)).where(
            PropertySnapshot.reporting_month_id == month_id
        )
    )
    return int(total or 0)


def list_property_snapshots(session: Session) -> list[PropertySnapshot]:
    return list(
        session.scalars(
            select(PropertySnapshot).order_by(
                PropertySnapshot.reporting_month_id, PropertySnapshot.id
            )
        )
    )


def get_property_snapshot(session: Session, snapshot_id: int) -> PropertySnapshot:
    snapshot = session.get(PropertySnapshot, snapshot_id)
    if snapshot is None:
        raise PropertySnapshotNotFoundError(f"property snapshot {snapshot_id} was not found")
    return snapshot


def total_property_value(session: Session, reporting_month_id: int) -> RubleAmount:
    return RubleAmount(
        _sum_field(session, reporting_month_id, PropertySnapshot.estimated_value_kopecks)
    )


def total_mortgage_balance(session: Session, reporting_month_id: int) -> RubleAmount:
    return RubleAmount(
        _sum_field(session, reporting_month_id, PropertySnapshot.mortgage_balance_kopecks)
    )


def property_equity(session: Session, reporting_month_id: int) -> RubleAmount:
    value = total_property_value(session, reporting_month_id)
    mortgage = total_mortgage_balance(session, reporting_month_id)
    return RubleAmount(value.kopecks - mortgage.kopecks)


def mortgage_coverage(
    session: Session,
    reporting_month_id: int,
    liquid_capital_net: RubleAmount,
) -> tuple[Decimal | None, RubleAmount]:
    mortgage = total_mortgage_balance(session, reporting_month_id)
    gap = RubleAmount(liquid_capital_net.kopecks - mortgage.kopecks)
    if mortgage.kopecks == 0:
        return None, gap
    percentage = (
        Decimal(liquid_capital_net.kopecks) / Decimal(mortgage.kopecks) * Decimal(100)
    ).quantize(Decimal("0.01"), rounding=FINANCIAL_ROUNDING)
    return percentage, gap


def create_property_snapshot(
    session: Session,
    *,
    reporting_month_id: int,
    name: str,
    estimated_value: RubleAmount | str,
    mortgage_balance: RubleAmount | str,
    monthly_payment: RubleAmount | str,
    notes: str | None = None,
) -> PropertySnapshot:
    require_editable_reporting_month(session, reporting_month_id)
    snapshot = PropertySnapshot(
        reporting_month_id=reporting_month_id,
        name=_normalize_text(name, field="name"),
        estimated_value_kopecks=_normalize_amount(estimated_value, field="estimated_value"),
        mortgage_balance_kopecks=_normalize_amount(mortgage_balance, field="mortgage_balance"),
        monthly_payment_kopecks=_normalize_amount(monthly_payment, field="monthly_payment"),
        notes=notes,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def update_property_snapshot(
    session: Session,
    snapshot_id: int,
    *,
    name: str | None = None,
    estimated_value: RubleAmount | str | None = None,
    mortgage_balance: RubleAmount | str | None = None,
    monthly_payment: RubleAmount | str | None = None,
    notes: str | None = None,
) -> PropertySnapshot:
    snapshot = get_property_snapshot(session, snapshot_id)
    require_editable_child_month(session, snapshot)
    if name is not None:
        snapshot.name = _normalize_text(name, field="name")
    if estimated_value is not None:
        snapshot.estimated_value_kopecks = _normalize_amount(
            estimated_value, field="estimated_value"
        )
    if mortgage_balance is not None:
        snapshot.mortgage_balance_kopecks = _normalize_amount(
            mortgage_balance, field="mortgage_balance"
        )
    if monthly_payment is not None:
        snapshot.monthly_payment_kopecks = _normalize_amount(
            monthly_payment, field="monthly_payment"
        )
    if notes is not None:
        snapshot.notes = notes
    session.commit()
    session.refresh(snapshot)
    return snapshot


def delete_property_snapshot(session: Session, snapshot_id: int) -> None:
    snapshot = get_property_snapshot(session, snapshot_id)
    require_editable_child_month(session, snapshot)
    session.delete(snapshot)
    session.commit()
