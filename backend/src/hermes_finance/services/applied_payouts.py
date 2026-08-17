"""Applied provider-payout persistence primitives (R05-04).

Schema/repository only. These helpers do not fetch provider data, preview,
apply a selected set, merge the calendar, or mutate manual
``expected_cash_flows`` rows. Callers own the transaction: writes flush and
do not commit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount
from hermes_finance.market_data.payout import (
    PayoutEventKind,
    normalize_currency,
    normalize_exact_decimal,
)
from hermes_finance.persistence import (
    Account,
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    ExpectedCashFlow,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.expected_cash_flows import ExpectedCashFlowNotFoundError
from hermes_finance.services.instruments import InstrumentNotFoundError
from hermes_finance.services.positions import PositionSnapshotNotFoundError


class AppliedPayoutAlreadyExistsError(ValueError):
    pass


class AppliedPayoutNotFoundError(LookupError):
    pass


class AppliedPayoutRevisionError(ValueError):
    """Raised when a caller tries to treat a historical revision as mutable."""


class AppliedPayoutLifecycle(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    DISMISSED = "dismissed"


class AppliedPayoutRevisionKind(StrEnum):
    APPLY = "apply"
    REVISE = "revise"
    CANCEL = "cancel"
    DISMISS = "dismiss"


class PayoutAmountBasis(StrEnum):
    PROVIDER_ANNOUNCED = "provider_announced"


class PayoutCountingDecision(StrEnum):
    KEEP_BOTH = "keep_both"
    COUNT_MANUAL = "count_manual"
    COUNT_PROVIDER = "count_provider"


_FORBIDDEN_PAYLOAD_MARKERS = (
    "raw_payload",
    "raw_json",
    "payload_json",
    "response_body",
    "raw_response",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "account_discovery",
    "broker_account_id",
)


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _require_instrument(session: Session, instrument_id: int) -> None:
    if session.get(Instrument, instrument_id) is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")


def _require_text(value: str, *, name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _require_date(value: date, *, name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{name} must be a date")
    return value


def _require_timestamp(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _canonical_decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _normalize_per_unit(value: Decimal | int | str) -> Decimal:
    amount = normalize_exact_decimal(value)
    if amount is None:
        raise ValueError("per_unit_amount is required")
    if amount < 0:
        raise ValueError("per_unit_amount must not be negative")
    return amount


def _normalize_rub_currency(value: str) -> str:
    currency = normalize_currency(value)
    if currency != "RUB":
        raise ValueError("foreign currency provider payouts are not persisted in R05")
    return currency


def _coerce_event_kind(value: PayoutEventKind | str) -> PayoutEventKind:
    try:
        return PayoutEventKind(value)
    except ValueError as error:
        raise ValueError(f"unsupported payout event kind: {value!r}") from error


def _coerce_lifecycle(value: AppliedPayoutLifecycle | str) -> AppliedPayoutLifecycle:
    try:
        return AppliedPayoutLifecycle(value)
    except ValueError as error:
        raise ValueError(f"unsupported applied payout lifecycle: {value!r}") from error


def _coerce_revision_kind(value: AppliedPayoutRevisionKind | str) -> AppliedPayoutRevisionKind:
    try:
        return AppliedPayoutRevisionKind(value)
    except ValueError as error:
        raise ValueError(f"unsupported payout revision kind: {value!r}") from error


def _coerce_amount_basis(value: PayoutAmountBasis | str) -> PayoutAmountBasis:
    try:
        return PayoutAmountBasis(value)
    except ValueError as error:
        raise ValueError(f"unsupported payout amount basis: {value!r}") from error


def _coerce_counting_decision(value: PayoutCountingDecision | str) -> PayoutCountingDecision:
    try:
        return PayoutCountingDecision(value)
    except ValueError as error:
        raise ValueError(f"unsupported payout counting decision: {value!r}") from error


def _freeze_snapshot(
    session: Session,
    *,
    snapshot_id: int,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
) -> PositionSnapshot:
    snapshot = session.get(PositionSnapshot, snapshot_id)
    if snapshot is None:
        raise PositionSnapshotNotFoundError(f"position snapshot {snapshot_id} was not found")
    if (
        snapshot.reporting_month_id != reporting_month_id
        or snapshot.account_id != account_id
        or snapshot.instrument_id != instrument_id
    ):
        raise ValueError(
            "source position snapshot must match the payout month, account and instrument"
        )
    return snapshot


def compute_applied_total_kopecks(per_unit_amount: Decimal, quantity: Decimal) -> int:
    """ROUND_HALF_UP(per_unit * quantity) to 0.01 RUB, stored as integer kopecks."""

    if isinstance(per_unit_amount, float) or isinstance(quantity, float):
        raise TypeError("binary float is forbidden for payout quantity and per-unit amount")
    return RubleAmount.from_decimal(per_unit_amount * quantity).kopecks


def get_applied_payout(session: Session, payout_id: int) -> AppliedProviderPayout:
    payout = session.get(AppliedProviderPayout, payout_id)
    if payout is None:
        raise AppliedPayoutNotFoundError(f"applied provider payout {payout_id} was not found")
    return payout


def get_applied_payout_by_identity(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    provider: str,
    provider_instrument_uid: str,
    event_kind: PayoutEventKind | str,
    identity_key: str,
) -> AppliedProviderPayout | None:
    return session.scalar(
        select(AppliedProviderPayout).where(
            AppliedProviderPayout.reporting_month_id == reporting_month_id,
            AppliedProviderPayout.account_id == account_id,
            AppliedProviderPayout.instrument_id == instrument_id,
            AppliedProviderPayout.provider == provider,
            AppliedProviderPayout.provider_instrument_uid == provider_instrument_uid,
            AppliedProviderPayout.event_kind == _coerce_event_kind(event_kind).value,
            AppliedProviderPayout.identity_key == identity_key,
        )
    )


def list_applied_payout_revisions(
    session: Session, applied_payout_id: int
) -> list[AppliedPayoutRevision]:
    get_applied_payout(session, applied_payout_id)
    return list(
        session.scalars(
            select(AppliedPayoutRevision)
            .where(AppliedPayoutRevision.applied_payout_id == applied_payout_id)
            .order_by(AppliedPayoutRevision.id)
        )
    )


def get_applied_payout_reconciliation(
    session: Session, applied_payout_id: int
) -> AppliedPayoutReconciliation | None:
    get_applied_payout(session, applied_payout_id)
    return session.scalar(
        select(AppliedPayoutReconciliation).where(
            AppliedPayoutReconciliation.applied_payout_id == applied_payout_id
        )
    )


def _append_revision_row(
    session: Session,
    *,
    payout: AppliedProviderPayout,
    revision_kind: AppliedPayoutRevisionKind,
    snapshot: PositionSnapshot,
    payment_date: date,
    per_unit_text: str,
    total_amount_kopecks: int,
    currency: str,
    amount_basis: PayoutAmountBasis,
    is_approximate: bool,
    lifecycle: AppliedPayoutLifecycle,
    provider_status: str | None,
    fetched_at: datetime,
    applied_at: datetime,
) -> AppliedPayoutRevision:
    revision = AppliedPayoutRevision(
        applied_payout_id=payout.id,
        revision_kind=revision_kind.value,
        source_position_snapshot_id=snapshot.id,
        provider=payout.provider,
        provider_instrument_uid=payout.provider_instrument_uid,
        event_kind=payout.event_kind,
        identity_key=payout.identity_key,
        lifecycle=lifecycle.value,
        payment_date=payment_date,
        quantity=snapshot.quantity,
        per_unit_amount=per_unit_text,
        total_amount_kopecks=total_amount_kopecks,
        currency=currency,
        amount_basis=amount_basis.value,
        is_approximate=is_approximate,
        provider_status=provider_status,
        fetched_at=fetched_at,
        applied_at=applied_at,
    )
    session.add(revision)
    return revision


def create_applied_payout(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    source_position_snapshot_id: int,
    provider: str,
    provider_instrument_uid: str,
    event_kind: PayoutEventKind | str,
    identity_key: str,
    payment_date: date,
    per_unit_amount: Decimal | int | str,
    currency: str,
    fetched_at: datetime,
    applied_at: datetime | None = None,
    provider_status: str | None = None,
    is_approximate: bool = True,
    amount_basis: PayoutAmountBasis | str = PayoutAmountBasis.PROVIDER_ANNOUNCED,
    lifecycle: AppliedPayoutLifecycle | str = AppliedPayoutLifecycle.ACTIVE,
) -> AppliedProviderPayout:
    require_editable_reporting_month(session, reporting_month_id)
    _require_account(session, account_id)
    _require_instrument(session, instrument_id)
    snapshot = _freeze_snapshot(
        session,
        snapshot_id=source_position_snapshot_id,
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
    )
    kind = _coerce_event_kind(event_kind)
    provider_name = _require_text(provider, name="provider")
    uid = _require_text(provider_instrument_uid, name="provider_instrument_uid")
    key = _require_text(identity_key, name="identity_key")
    existing = get_applied_payout_by_identity(
        session,
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        provider=provider_name,
        provider_instrument_uid=uid,
        event_kind=kind,
        identity_key=key,
    )
    if existing is not None:
        raise AppliedPayoutAlreadyExistsError(
            "applied provider payout already exists for this identity "
            "in the month/account/instrument scope"
        )
    accepted_at = _require_timestamp(applied_at or datetime.now(UTC), name="applied_at")
    per_unit = _normalize_per_unit(per_unit_amount)
    per_unit_text = _canonical_decimal_text(per_unit)
    rub = _normalize_rub_currency(currency)
    total = compute_applied_total_kopecks(per_unit, snapshot.quantity)
    status = (
        _require_text(provider_status, name="provider_status")
        if provider_status is not None
        else None
    )
    payout = AppliedProviderPayout(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        source_position_snapshot_id=snapshot.id,
        provider=provider_name,
        provider_instrument_uid=uid,
        event_kind=kind.value,
        identity_key=key,
        lifecycle=_coerce_lifecycle(lifecycle).value,
        payment_date=_require_date(payment_date, name="payment_date"),
        quantity=snapshot.quantity,
        per_unit_amount=per_unit_text,
        total_amount_kopecks=total,
        currency=rub,
        amount_basis=_coerce_amount_basis(amount_basis).value,
        is_approximate=is_approximate,
        provider_status=status,
        first_applied_at=accepted_at,
    )
    session.add(payout)
    try:
        session.flush()
    except IntegrityError as error:
        raise AppliedPayoutAlreadyExistsError(
            "applied provider payout already exists for this identity "
            "in the month/account/instrument scope"
        ) from error
    _append_revision_row(
        session,
        payout=payout,
        revision_kind=AppliedPayoutRevisionKind.APPLY,
        snapshot=snapshot,
        payment_date=payout.payment_date,
        per_unit_text=per_unit_text,
        total_amount_kopecks=total,
        currency=rub,
        amount_basis=_coerce_amount_basis(amount_basis),
        is_approximate=is_approximate,
        lifecycle=_coerce_lifecycle(lifecycle),
        provider_status=status,
        fetched_at=_require_timestamp(fetched_at, name="fetched_at"),
        applied_at=accepted_at,
    )
    session.flush()
    return payout


def append_applied_payout_revision(
    session: Session,
    applied_payout_id: int,
    *,
    revision_kind: AppliedPayoutRevisionKind | str,
    fetched_at: datetime,
    applied_at: datetime | None = None,
    payment_date: date | None = None,
    per_unit_amount: Decimal | int | str | None = None,
    currency: str | None = None,
    source_position_snapshot_id: int | None = None,
    provider_status: str | None = None,
    is_approximate: bool | None = None,
    amount_basis: PayoutAmountBasis | str | None = None,
    lifecycle: AppliedPayoutLifecycle | str | None = None,
) -> AppliedPayoutRevision:
    payout = get_applied_payout(session, applied_payout_id)
    require_editable_reporting_month(session, payout.reporting_month_id)
    kind = _coerce_revision_kind(revision_kind)
    if kind is AppliedPayoutRevisionKind.APPLY:
        raise AppliedPayoutRevisionError(
            "first apply is recorded by create_applied_payout; later history must not reuse apply"
        )
    snapshot = _freeze_snapshot(
        session,
        snapshot_id=source_position_snapshot_id or payout.source_position_snapshot_id,
        reporting_month_id=payout.reporting_month_id,
        account_id=payout.account_id,
        instrument_id=payout.instrument_id,
    )
    next_date = (
        _require_date(payment_date, name="payment_date")
        if payment_date is not None
        else payout.payment_date
    )
    per_unit = (
        _normalize_per_unit(per_unit_amount)
        if per_unit_amount is not None
        else normalize_exact_decimal(payout.per_unit_amount)
    )
    if per_unit is None:
        raise ValueError("per_unit_amount is required")
    per_unit_text = _canonical_decimal_text(per_unit)
    rub = _normalize_rub_currency(currency) if currency is not None else payout.currency
    total = compute_applied_total_kopecks(per_unit, snapshot.quantity)
    if lifecycle is None:
        next_lifecycle = AppliedPayoutLifecycle(payout.lifecycle)
    else:
        next_lifecycle = _coerce_lifecycle(lifecycle)
    if kind is AppliedPayoutRevisionKind.CANCEL:
        next_lifecycle = AppliedPayoutLifecycle.CANCELLED
    elif kind is AppliedPayoutRevisionKind.DISMISS:
        next_lifecycle = AppliedPayoutLifecycle.DISMISSED
    next_basis = (
        _coerce_amount_basis(amount_basis)
        if amount_basis is not None
        else PayoutAmountBasis(payout.amount_basis)
    )
    next_approximate = payout.is_approximate if is_approximate is None else is_approximate
    if provider_status is None:
        status = payout.provider_status
    else:
        status = _require_text(provider_status, name="provider_status")
    accepted_at = _require_timestamp(applied_at or datetime.now(UTC), name="applied_at")

    payout.source_position_snapshot_id = snapshot.id
    payout.payment_date = next_date
    payout.quantity = snapshot.quantity
    payout.per_unit_amount = per_unit_text
    payout.total_amount_kopecks = total
    payout.currency = rub
    payout.amount_basis = next_basis.value
    payout.is_approximate = next_approximate
    payout.lifecycle = next_lifecycle.value
    payout.provider_status = status

    revision = _append_revision_row(
        session,
        payout=payout,
        revision_kind=kind,
        snapshot=snapshot,
        payment_date=next_date,
        per_unit_text=per_unit_text,
        total_amount_kopecks=total,
        currency=rub,
        amount_basis=next_basis,
        is_approximate=next_approximate,
        lifecycle=next_lifecycle,
        provider_status=status,
        fetched_at=_require_timestamp(fetched_at, name="fetched_at"),
        applied_at=accepted_at,
    )
    session.flush()
    return revision


def update_applied_payout_revision(*_args: object, **_kwargs: object) -> None:
    raise AppliedPayoutRevisionError("applied payout revisions are append-only")


def overwrite_applied_payout_revision(*_args: object, **_kwargs: object) -> None:
    raise AppliedPayoutRevisionError("applied payout revisions are append-only")


def delete_applied_payout_revision(*_args: object, **_kwargs: object) -> None:
    raise AppliedPayoutRevisionError("applied payout revisions are append-only")


def set_applied_payout_reconciliation(
    session: Session,
    applied_payout_id: int,
    *,
    expected_cash_flow_id: int,
    counting_decision: PayoutCountingDecision | str,
) -> AppliedPayoutReconciliation:
    payout = get_applied_payout(session, applied_payout_id)
    require_editable_reporting_month(session, payout.reporting_month_id)
    flow = session.get(ExpectedCashFlow, expected_cash_flow_id)
    if flow is None:
        raise ExpectedCashFlowNotFoundError(
            f"expected cash flow {expected_cash_flow_id} was not found"
        )
    if (
        flow.reporting_month_id != payout.reporting_month_id
        or flow.account_id != payout.account_id
        or flow.instrument_id != payout.instrument_id
    ):
        raise ValueError(
            "manual expected cash flow must match the payout month, account and instrument"
        )
    decision = _coerce_counting_decision(counting_decision)
    link = get_applied_payout_reconciliation(session, applied_payout_id)
    if link is None:
        link = AppliedPayoutReconciliation(
            applied_payout_id=payout.id,
            expected_cash_flow_id=flow.id,
            counting_decision=decision.value,
        )
        session.add(link)
    else:
        link.expected_cash_flow_id = flow.id
        link.counting_decision = decision.value
    session.flush()
    return link


def clear_applied_payout_reconciliation(session: Session, applied_payout_id: int) -> None:
    payout = get_applied_payout(session, applied_payout_id)
    require_editable_reporting_month(session, payout.reporting_month_id)
    link = get_applied_payout_reconciliation(session, applied_payout_id)
    if link is None:
        return
    session.delete(link)
    session.flush()


def assert_no_raw_provider_payload_columns() -> None:
    """Test helper: persistence tables must not store tokens or raw payloads."""

    for model in (
        AppliedProviderPayout,
        AppliedPayoutRevision,
        AppliedPayoutReconciliation,
    ):
        names = {column.name for column in model.__table__.columns}
        forbidden = names.intersection(_FORBIDDEN_PAYLOAD_MARKERS)
        if forbidden:
            raise AssertionError(
                f"{model.__tablename__} has forbidden columns: {sorted(forbidden)}"
            )
