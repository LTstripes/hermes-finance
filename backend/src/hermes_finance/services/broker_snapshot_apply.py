"""Owner-confirmed broker snapshot quantity apply (R06-05).

Alfa/provider quantity may become Hermes PositionSnapshot quantity only after
explicit owner selection. Dependent Hermes semantics remain local/owner-supplied.
No persistent provider mappings, cash writes, account/instrument creation,
direct provider price/UchPrice/NKD/P&L overwrite, or trading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.orm import Session

from hermes_finance.broker_data.dto import BrokerSnapshot, SnapshotStatus
from hermes_finance.broker_data.protocol import BrokerSnapshotProvider
from hermes_finance.broker_data.reconciliation.dto import (
    OwnerMappingInput,
    PositionReconciliationRow,
    PositionRowStatus,
    ReconciliationPreview,
)
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview
from hermes_finance.domain import PriceSource, RubleAmount
from hermes_finance.persistence import PositionSnapshot
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.broker_identity_mappings import compose_owner_mapping
from hermes_finance.services.broker_reconciliation import load_hermes_state_for_month
from hermes_finance.services.positions import (
    get_position_snapshot_by_key,
    stage_create_position_snapshot,
    stage_update_position_snapshot,
)
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    ReportingMonthNotFoundError,
)


class BrokerSnapshotApplyFailureCode(StrEnum):
    PREVIEW_CHANGED = "preview_changed"
    VALIDATION_ERROR = "validation_error"
    PROVIDER_ERROR = "provider_error"
    PERSISTENCE_ERROR = "persistence_error"
    CLOSED_MONTH = "closed_month"


class BrokerSnapshotApplyAction(StrEnum):
    UPDATE = "update"
    CREATE = "create"


class DependentFieldAction(StrEnum):
    KEEP_EXISTING = "keep_existing"
    REPLACE = "replace"


class BrokerSnapshotApplyItemAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def _coerce_action(value: DependentFieldAction | str, *, field: str) -> DependentFieldAction:
    try:
        return DependentFieldAction(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} action is invalid") from error


@dataclass(frozen=True, slots=True)
class AverageCostDecision:
    action: DependentFieldAction
    value: RubleAmount | str | int | None = None

    def __post_init__(self) -> None:
        action = _coerce_action(self.action, field="average_cost")
        object.__setattr__(self, "action", action)
        if action is DependentFieldAction.REPLACE and self.value is None:
            raise ValueError("average_cost replace requires an explicit local value")
        if action is DependentFieldAction.KEEP_EXISTING and self.value is not None:
            raise ValueError("average_cost keep_existing must not include a replacement value")


@dataclass(frozen=True, slots=True)
class MarketPriceDecision:
    action: DependentFieldAction
    market_price_per_unit: RubleAmount | str | int | None = None
    price_date: date | None = None
    price_source: PriceSource | str | None = None

    def __post_init__(self) -> None:
        action = _coerce_action(self.action, field="market_price")
        object.__setattr__(self, "action", action)
        if action is DependentFieldAction.REPLACE:
            if (
                self.market_price_per_unit is None
                or self.price_date is None
                or self.price_source is None
            ):
                raise ValueError(
                    "market_price replace requires explicit local price, date and source"
                )
        elif (
            self.market_price_per_unit is not None
            or self.price_date is not None
            or self.price_source is not None
        ):
            raise ValueError("market_price keep_existing must not include replacement fields")


@dataclass(frozen=True, slots=True)
class AccruedInterestDecision:
    action: DependentFieldAction
    value: RubleAmount | str | int | None = None

    def __post_init__(self) -> None:
        action = _coerce_action(self.action, field="accrued_interest")
        object.__setattr__(self, "action", action)
        if action is DependentFieldAction.REPLACE and self.value is None:
            raise ValueError("accrued_interest replace requires an explicit local value")
        if action is DependentFieldAction.KEEP_EXISTING and self.value is not None:
            raise ValueError("accrued_interest keep_existing must not include a replacement value")


@dataclass(frozen=True, slots=True)
class BrokerSnapshotApplySelection:
    account_id: int
    instrument_id: int
    fingerprint: str
    action: BrokerSnapshotApplyAction
    average_cost: AverageCostDecision | None = None
    market_price: MarketPriceDecision | None = None
    accrued_interest: AccruedInterestDecision | None = None

    def __post_init__(self) -> None:
        try:
            action = BrokerSnapshotApplyAction(self.action)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported broker snapshot apply action") from error
        object.__setattr__(self, "action", action)
        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise ValueError("account_id must be a positive integer")
        if (
            isinstance(self.instrument_id, bool)
            or not isinstance(self.instrument_id, int)
            or self.instrument_id <= 0
        ):
            raise ValueError("instrument_id must be a positive integer")
        if not isinstance(self.fingerprint, str) or not self.fingerprint.strip():
            raise ValueError("fingerprint must not be empty")
        object.__setattr__(self, "fingerprint", self.fingerprint.strip())


@dataclass(frozen=True, slots=True)
class BrokerSnapshotApplyItemResult:
    action: BrokerSnapshotApplyItemAction
    position_snapshot_id: int
    account_id: int
    instrument_id: int
    quantity: Decimal
    average_cost_per_unit_kopecks: int
    market_price_per_unit_kopecks: int
    accrued_interest_kopecks: int | None
    market_value_kopecks: int
    cost_basis_kopecks: int
    unrealized_result_kopecks: int
    price_date: date
    price_source: str


@dataclass(frozen=True, slots=True)
class BrokerSnapshotApplyResult:
    success: bool
    selected_count: int
    items: tuple[BrokerSnapshotApplyItemResult, ...] = ()
    error_code: BrokerSnapshotApplyFailureCode | None = None
    message: str | None = None
    source_as_of: datetime | None = None
    captured_at: datetime | None = None
    snapshot_status: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class _ApplyPlan:
    selection: BrokerSnapshotApplySelection
    row: PositionReconciliationRow
    snapshot: PositionSnapshot | None
    quantity: Decimal
    no_op: bool


_APPLYABLE_STATUSES = {PositionRowStatus.MATCHED, PositionRowStatus.PROVIDER_ONLY}


def keep_existing_average_cost() -> AverageCostDecision:
    return AverageCostDecision(action=DependentFieldAction.KEEP_EXISTING)


def keep_existing_market_price() -> MarketPriceDecision:
    return MarketPriceDecision(action=DependentFieldAction.KEEP_EXISTING)


def keep_existing_accrued_interest() -> AccruedInterestDecision:
    return AccruedInterestDecision(action=DependentFieldAction.KEEP_EXISTING)


def position_apply_fingerprint(
    *,
    preview: ReconciliationPreview,
    row: PositionReconciliationRow,
    mapping: OwnerMappingInput,
    snapshot: PositionSnapshot | None,
) -> str:
    """Deterministic material fingerprint for stale-preview protection.

    Display-only / non-comparable provider observations (Price, UchPrice, NKD,
    unrealized, ticker, name) are excluded. Mapping scope is hashed, not stored.
    """
    payload = {
        "account_id": row.account_id,
        "instrument_id": row.instrument_id,
        "position_status": row.status.value,
        "provider_quantity": _canonical_decimal(row.provider_quantity),
        "snapshot_status": preview.snapshot_status.value,
        "eligible_for_apply": preview.eligible_for_apply,
        "provider": preview.provider,
        "month_id": preview.month_id,
        "month_status": preview.month_status,
        "mapping": _mapping_scope(mapping),
        "local": _local_fingerprint_state(snapshot),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def apply_broker_snapshot_preview(
    session: Session,
    *,
    provider: BrokerSnapshotProvider,
    reporting_month_id: int,
    mapping: OwnerMappingInput,
    selections: tuple[BrokerSnapshotApplySelection, ...],
) -> BrokerSnapshotApplyResult:
    """Re-fetch, rebuild R06-04 preview, and atomically apply the selected set."""

    selected_count = len(selections)
    if not selections:
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
            "at least one broker snapshot row must be selected",
        )
    if session.new or session.dirty or session.deleted:
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
            "broker snapshot apply requires a clean database session",
        )
    if _has_duplicate_selections(selections):
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
            "selected account and instrument identities must be unique",
        )

    try:
        with session.no_autoflush:
            require_editable_reporting_month(session, reporting_month_id)
    except ClosedReportingMonthError:
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.CLOSED_MONTH,
            "closed reporting month must be reopened before broker snapshot apply",
        )
    except ReportingMonthNotFoundError:
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
            "reporting month was not found",
        )

    # Expire cached ORM state before provider I/O so the rebuilt preview reads
    # current PositionSnapshot rows from SQLite rather than a stale identity map.
    session.rollback()

    try:
        snapshot = provider.fetch_snapshot()
    except Exception:
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.PROVIDER_ERROR,
            "broker snapshot provider refresh failed",
        )
    if not isinstance(snapshot, BrokerSnapshot):
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.PROVIDER_ERROR,
            "broker snapshot provider refresh failed",
        )

    hermes = load_hermes_state_for_month(session, reporting_month_id)
    mapping = compose_owner_mapping(session, provider=snapshot.provider, request=mapping)
    fresh_preview = build_reconciliation_preview(
        snapshot=snapshot,
        hermes=hermes,
        mapping=mapping,
    )
    if (
        fresh_preview.snapshot_status is not SnapshotStatus.COMPLETE
        or not fresh_preview.eligible_for_apply
    ):
        return _preview_changed(selected_count)

    plan_result = _build_apply_plan(
        session,
        reporting_month_id=reporting_month_id,
        preview=fresh_preview,
        mapping=mapping,
        selections=selections,
    )
    if isinstance(plan_result, BrokerSnapshotApplyResult):
        return plan_result
    plans = plan_result

    item_results: list[BrokerSnapshotApplyItemResult] = []
    try:
        wrote = False
        for plan in plans:
            if plan.no_op:
                assert plan.snapshot is not None
                item_results.append(
                    _item_from_snapshot(plan.snapshot, BrokerSnapshotApplyItemAction.UNCHANGED)
                )
                continue
            if plan.selection.action is BrokerSnapshotApplyAction.CREATE:
                created = _stage_create(session, reporting_month_id, plan)
                item_results.append(
                    _item_from_snapshot(created, BrokerSnapshotApplyItemAction.CREATED)
                )
            else:
                updated = _stage_update(session, plan)
                item_results.append(
                    _item_from_snapshot(updated, BrokerSnapshotApplyItemAction.UPDATED)
                )
            wrote = True
        if wrote:
            session.commit()
    except Exception:
        session.rollback()
        return _failure(
            selected_count,
            BrokerSnapshotApplyFailureCode.PERSISTENCE_ERROR,
            "broker snapshot apply persistence failed",
        )

    for item in item_results:
        session.refresh(session.get(PositionSnapshot, item.position_snapshot_id))

    return BrokerSnapshotApplyResult(
        success=True,
        selected_count=selected_count,
        items=tuple(item_results),
        source_as_of=fresh_preview.source_as_of,
        captured_at=fresh_preview.captured_at,
        snapshot_status=fresh_preview.snapshot_status.value,
        fingerprint=_preview_evidence_fingerprint(fresh_preview),
    )


def _build_apply_plan(
    session: Session,
    *,
    reporting_month_id: int,
    preview: ReconciliationPreview,
    mapping: OwnerMappingInput,
    selections: tuple[BrokerSnapshotApplySelection, ...],
) -> tuple[_ApplyPlan, ...] | BrokerSnapshotApplyResult:
    by_identity: dict[tuple[int, int], list[PositionReconciliationRow]] = {}
    for row in preview.positions:
        by_identity.setdefault((row.account_id, row.instrument_id), []).append(row)

    selected_count = len(selections)
    plans: list[_ApplyPlan] = []
    for selection in selections:
        matches = by_identity.get((selection.account_id, selection.instrument_id), [])
        if len(matches) != 1:
            return _preview_changed(selected_count)
        row = matches[0]
        local = get_position_snapshot_by_key(
            session,
            reporting_month_id=reporting_month_id,
            account_id=selection.account_id,
            instrument_id=selection.instrument_id,
        )
        fingerprint = position_apply_fingerprint(
            preview=preview,
            row=row,
            mapping=mapping,
            snapshot=local,
        )
        if fingerprint != selection.fingerprint:
            return _preview_changed(selected_count)
        if row.status not in _APPLYABLE_STATUSES:
            return _failure(
                selected_count,
                BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
                "selected position is not applyable",
            )

        try:
            plan = _plan_row(selection, row, local)
        except ValueError as error:
            return _failure(
                selected_count,
                BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
                str(error),
            )
        plans.append(plan)
    return tuple(plans)


def _plan_row(
    selection: BrokerSnapshotApplySelection,
    row: PositionReconciliationRow,
    snapshot: PositionSnapshot | None,
) -> _ApplyPlan:
    quantity = row.provider_quantity
    if quantity is None or not isinstance(quantity, Decimal) or not quantity.is_finite():
        raise ValueError("provider quantity is missing or invalid")
    if quantity <= 0:
        raise ValueError("zero or missing provider quantity cannot be applied")

    if selection.action is BrokerSnapshotApplyAction.UPDATE:
        if row.status is not PositionRowStatus.MATCHED or snapshot is None:
            raise ValueError("update requires a matched existing PositionSnapshot")
        _require_update_decisions(selection)
        no_op = _is_update_noop(selection, snapshot, quantity)
        return _ApplyPlan(
            selection=selection,
            row=row,
            snapshot=snapshot,
            quantity=quantity,
            no_op=no_op,
        )

    if selection.action is BrokerSnapshotApplyAction.CREATE:
        if row.status is not PositionRowStatus.PROVIDER_ONLY or snapshot is not None:
            raise ValueError("create requires a resolved provider-only position")
        _require_create_inputs(selection)
        return _ApplyPlan(
            selection=selection,
            row=row,
            snapshot=None,
            quantity=quantity,
            no_op=False,
        )

    raise ValueError("unsupported broker snapshot apply action")


def _require_update_decisions(selection: BrokerSnapshotApplySelection) -> None:
    if (
        selection.average_cost is None
        or selection.market_price is None
        or selection.accrued_interest is None
    ):
        raise ValueError(
            "quantity apply requires explicit average_cost, market_price and "
            "accrued_interest owner decisions"
        )


def _require_create_inputs(selection: BrokerSnapshotApplySelection) -> None:
    if (
        selection.average_cost is None
        or selection.average_cost.action is not DependentFieldAction.REPLACE
    ):
        raise ValueError("provider-only create requires an explicit local average_cost")
    if (
        selection.market_price is None
        or selection.market_price.action is not DependentFieldAction.REPLACE
    ):
        raise ValueError(
            "provider-only create requires an explicit local market price, date and source"
        )
    if (
        selection.accrued_interest is not None
        and selection.accrued_interest.action is DependentFieldAction.KEEP_EXISTING
    ):
        raise ValueError("provider-only create cannot keep_existing accrued_interest")


def _is_update_noop(
    selection: BrokerSnapshotApplySelection,
    snapshot: PositionSnapshot,
    quantity: Decimal,
) -> bool:
    assert selection.average_cost is not None
    assert selection.market_price is not None
    assert selection.accrued_interest is not None
    if Decimal(snapshot.quantity) != quantity:
        return False
    if selection.average_cost.action is DependentFieldAction.REPLACE:
        return False
    if selection.market_price.action is DependentFieldAction.REPLACE:
        return False
    if selection.accrued_interest.action is DependentFieldAction.REPLACE:
        return False
    return True


def _stage_create(
    session: Session,
    reporting_month_id: int,
    plan: _ApplyPlan,
) -> PositionSnapshot:
    selection = plan.selection
    assert selection.average_cost is not None and selection.average_cost.value is not None
    assert selection.market_price is not None
    assert selection.market_price.market_price_per_unit is not None
    assert selection.market_price.price_date is not None
    assert selection.market_price.price_source is not None
    accrued = None
    if selection.accrued_interest is not None:
        accrued = selection.accrued_interest.value
    return stage_create_position_snapshot(
        session,
        reporting_month_id=reporting_month_id,
        account_id=selection.account_id,
        instrument_id=selection.instrument_id,
        quantity=plan.quantity,
        average_cost_per_unit=selection.average_cost.value,
        market_price_per_unit=selection.market_price.market_price_per_unit,
        accrued_interest=accrued,
        price_date=selection.market_price.price_date,
        price_source=selection.market_price.price_source,
    )


def _stage_update(session: Session, plan: _ApplyPlan) -> PositionSnapshot:
    selection = plan.selection
    snapshot = plan.snapshot
    assert snapshot is not None
    assert selection.average_cost is not None
    assert selection.market_price is not None
    assert selection.accrued_interest is not None
    average_cost = (
        selection.average_cost.value
        if selection.average_cost.action is DependentFieldAction.REPLACE
        else None
    )
    market_price = None
    price_date = None
    price_source = None
    if selection.market_price.action is DependentFieldAction.REPLACE:
        market_price = selection.market_price.market_price_per_unit
        price_date = selection.market_price.price_date
        price_source = selection.market_price.price_source
    accrued = (
        selection.accrued_interest.value
        if selection.accrued_interest.action is DependentFieldAction.REPLACE
        else None
    )
    return stage_update_position_snapshot(
        session,
        snapshot.id,
        quantity=plan.quantity,
        average_cost_per_unit=average_cost,
        market_price_per_unit=market_price,
        accrued_interest=accrued,
        price_date=price_date,
        price_source=price_source,
        expected_updated_at=snapshot.updated_at,
    )


def _item_from_snapshot(
    snapshot: PositionSnapshot,
    action: BrokerSnapshotApplyItemAction,
) -> BrokerSnapshotApplyItemResult:
    return BrokerSnapshotApplyItemResult(
        action=action,
        position_snapshot_id=snapshot.id,
        account_id=snapshot.account_id,
        instrument_id=snapshot.instrument_id,
        quantity=Decimal(snapshot.quantity),
        average_cost_per_unit_kopecks=snapshot.average_cost_per_unit_kopecks,
        market_price_per_unit_kopecks=snapshot.market_price_per_unit_kopecks,
        accrued_interest_kopecks=snapshot.accrued_interest_kopecks,
        market_value_kopecks=snapshot.market_value_kopecks,
        cost_basis_kopecks=snapshot.cost_basis_kopecks,
        unrealized_result_kopecks=snapshot.unrealized_result_kopecks,
        price_date=snapshot.price_date,
        price_source=snapshot.price_source,
    )


def _has_duplicate_selections(selections: tuple[BrokerSnapshotApplySelection, ...]) -> bool:
    keys = [(item.account_id, item.instrument_id) for item in selections]
    return len(keys) != len(set(keys))


def _mapping_scope(mapping: OwnerMappingInput) -> dict[str, list[dict[str, object]]]:
    accounts = sorted(
        (
            {
                "hermes_account_id": item.hermes_account_id,
                "provider_account_id": item.provider_account_id,
            }
            for item in mapping.accounts
        ),
        key=lambda item: (item["hermes_account_id"], item["provider_account_id"]),
    )
    instruments = sorted(
        (
            {
                "hermes_instrument_id": item.hermes_instrument_id,
                "provider_instrument_id": item.provider_instrument_id,
            }
            for item in mapping.instruments
        ),
        key=lambda item: (item["hermes_instrument_id"], item["provider_instrument_id"]),
    )
    return {"accounts": accounts, "instruments": instruments}


def _local_fingerprint_state(snapshot: PositionSnapshot | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "position_snapshot_id": snapshot.id,
        "quantity": _canonical_decimal(Decimal(snapshot.quantity)),
        "average_cost_per_unit_kopecks": snapshot.average_cost_per_unit_kopecks,
        "market_price_per_unit_kopecks": snapshot.market_price_per_unit_kopecks,
        "accrued_interest_kopecks": snapshot.accrued_interest_kopecks,
        "price_date": snapshot.price_date.isoformat(),
        "price_source": snapshot.price_source,
        "updated_at": _canonical_datetime(snapshot.updated_at),
    }


def _preview_evidence_fingerprint(preview: ReconciliationPreview) -> str:
    payload = {
        "provider": preview.provider,
        "snapshot_status": preview.snapshot_status.value,
        "eligible_for_apply": preview.eligible_for_apply,
        "source_as_of": _canonical_datetime(preview.source_as_of) if preview.source_as_of else None,
        "month_id": preview.month_id,
        "month_status": preview.month_status,
        "conflict_count": preview.conflict_count,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_datetime(value: datetime) -> str:
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat()


def _preview_changed(selected_count: int) -> BrokerSnapshotApplyResult:
    return _failure(
        selected_count,
        BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED,
        "broker snapshot preview changed; refresh preview before applying",
    )


def _failure(
    selected_count: int,
    code: BrokerSnapshotApplyFailureCode,
    message: str,
) -> BrokerSnapshotApplyResult:
    return BrokerSnapshotApplyResult(
        success=False,
        selected_count=selected_count,
        error_code=code,
        message=message,
    )
