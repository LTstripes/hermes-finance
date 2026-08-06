from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import FINANCIAL_ROUNDING, DepositType, PercentageRate, RubleAmount
from hermes_finance.persistence import Account, DepositSnapshot, ReportingMonth
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class DepositSnapshotNotFoundError(LookupError):
    pass


def _require_reporting_month(session: Session, month_id: int) -> None:
    if session.get(ReportingMonth, month_id) is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("name must not be empty")
    return normalized


def _coerce_deposit_type(deposit_type: DepositType | str) -> DepositType:
    try:
        return DepositType(deposit_type)
    except ValueError as error:
        raise ValueError(f"unsupported deposit type: {deposit_type!r}") from error


def _normalize_balance(balance: RubleAmount | str) -> int:
    if isinstance(balance, str):
        balance = RubleAmount.from_api(balance)
    if not isinstance(balance, RubleAmount):
        raise TypeError("balance must be RubleAmount or decimal string")
    if balance.kopecks < 0:
        raise ValueError("balance must not be negative")
    return balance.kopecks


def _normalize_rate(annual_rate: PercentageRate | str) -> int:
    if isinstance(annual_rate, str):
        annual_rate = PercentageRate.from_api(annual_rate)
    if not isinstance(annual_rate, PercentageRate):
        raise TypeError("annual_rate must be PercentageRate or decimal string")
    if annual_rate.basis_points < 0:
        raise ValueError("annual_rate must not be negative")
    return annual_rate.basis_points


def _compute_expected_monthly_interest(balance_kopecks: int, annual_rate_basis_points: int) -> int:
    monthly = (
        Decimal(balance_kopecks) * Decimal(annual_rate_basis_points) / Decimal(10_000) / Decimal(12)
    )
    return int(monthly.to_integral_value(rounding=FINANCIAL_ROUNDING))


def list_deposit_snapshots(session: Session) -> list[DepositSnapshot]:
    return list(
        session.scalars(
            select(DepositSnapshot).order_by(
                DepositSnapshot.reporting_month_id, DepositSnapshot.account_id, DepositSnapshot.id
            )
        )
    )


def get_deposit_snapshot(session: Session, snapshot_id: int) -> DepositSnapshot:
    snapshot = session.get(DepositSnapshot, snapshot_id)
    if snapshot is None:
        raise DepositSnapshotNotFoundError(f"deposit snapshot {snapshot_id} was not found")
    return snapshot


def create_deposit_snapshot(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    name: str,
    deposit_type: DepositType | str,
    balance: RubleAmount | str,
    annual_rate: PercentageRate | str,
    actual_interest_received: RubleAmount | str = "0.00",
    notes: str | None = None,
) -> DepositSnapshot:
    _require_reporting_month(session, reporting_month_id)
    _require_account(session, account_id)
    balance_kopecks = _normalize_balance(balance)
    annual_rate_basis_points = _normalize_rate(annual_rate)
    snapshot = DepositSnapshot(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        name=_normalize_name(name),
        deposit_type=_coerce_deposit_type(deposit_type).value,
        balance_kopecks=balance_kopecks,
        annual_rate_basis_points=annual_rate_basis_points,
        expected_monthly_interest_kopecks=_compute_expected_monthly_interest(
            balance_kopecks, annual_rate_basis_points
        ),
        actual_interest_received_kopecks=_normalize_balance(actual_interest_received),
        notes=notes,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def update_deposit_snapshot(
    session: Session,
    snapshot_id: int,
    *,
    name: str | None = None,
    deposit_type: DepositType | str | None = None,
    balance: RubleAmount | str | None = None,
    annual_rate: PercentageRate | str | None = None,
    actual_interest_received: RubleAmount | str | None = None,
    notes: str | None = None,
) -> DepositSnapshot:
    snapshot = get_deposit_snapshot(session, snapshot_id)
    if name is not None:
        snapshot.name = _normalize_name(name)
    if deposit_type is not None:
        snapshot.deposit_type = _coerce_deposit_type(deposit_type).value
    if balance is not None:
        snapshot.balance_kopecks = _normalize_balance(balance)
    if annual_rate is not None:
        snapshot.annual_rate_basis_points = _normalize_rate(annual_rate)
    if actual_interest_received is not None:
        snapshot.actual_interest_received_kopecks = _normalize_balance(actual_interest_received)
    if notes is not None:
        snapshot.notes = notes

    snapshot.expected_monthly_interest_kopecks = _compute_expected_monthly_interest(
        snapshot.balance_kopecks, snapshot.annual_rate_basis_points
    )
    session.commit()
    session.refresh(snapshot)
    return snapshot


def delete_deposit_snapshot(session: Session, snapshot_id: int) -> None:
    snapshot = get_deposit_snapshot(session, snapshot_id)
    session.delete(snapshot)
    session.commit()
