"""Owner-managed external boundary-flow and transfer-link services.

This module deliberately does not calculate XIRR/TWRR or infer history from
legacy investment cash flows.  A transfer is complete only when the owner has
explicitly attached two opposite-direction legs for distinct accounts.  Date
and amount are stored as facts, never used as an implicit matching key.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, DecimalException
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    ExternalFlowClassification,
    ExternalFlowDirection,
    ExternalFlowKind,
    ExternalFlowScope,
    ExternalFlowScopeMembership,
    ExternalTransferStatus,
    RubleAmount,
)
from hermes_finance.persistence import Account, ExternalFlow, ExternalTransferLink
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)
from hermes_finance.services.accounts import AccountNotFoundError


class ExternalFlowNotFoundError(LookupError):
    pass


class ExternalTransferLinkNotFoundError(LookupError):
    pass


_UNSET = object()


def _normalize_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} must not exceed {max_length} characters")
    return normalized


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be a three-letter code")
    return normalized


def _normalize_exact_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        try:
            decimal_amount = Decimal(amount)
        except DecimalException as error:
            raise ValueError(f"{field} must be a finite decimal string") from error
        if not decimal_amount.is_finite():
            raise ValueError(f"{field} must be finite")
        scaled = decimal_amount * Decimal(100)
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{field} must have no more than two decimal places")
        amount = RubleAmount.from_decimal(decimal_amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _coerce_direction(direction: ExternalFlowDirection | str) -> ExternalFlowDirection:
    try:
        return ExternalFlowDirection(direction)
    except ValueError as error:
        raise ValueError(f"unsupported external flow direction: {direction!r}") from error


def _coerce_kind(kind: ExternalFlowKind | str) -> ExternalFlowKind:
    try:
        return ExternalFlowKind(kind)
    except ValueError as error:
        raise ValueError(f"unsupported external flow kind: {kind!r}") from error


def _coerce_scope_membership(
    scope_membership: ExternalFlowScopeMembership | str,
) -> ExternalFlowScopeMembership:
    try:
        return ExternalFlowScopeMembership(scope_membership)
    except ValueError as error:
        raise ValueError(
            f"unsupported external flow scope membership: {scope_membership!r}"
        ) from error


def _kind_for_direction(direction: ExternalFlowDirection) -> ExternalFlowKind:
    if direction is ExternalFlowDirection.CONTRIBUTION:
        return ExternalFlowKind.EXTERNAL_CONTRIBUTION
    return ExternalFlowKind.EXTERNAL_WITHDRAWAL


def _normalize_kind_direction(
    kind: ExternalFlowKind | str | None,
    direction: ExternalFlowDirection | str | None,
) -> tuple[ExternalFlowKind, ExternalFlowDirection]:
    normalized_kind = _coerce_kind(kind) if kind is not None else None
    normalized_direction = _coerce_direction(direction) if direction is not None else None
    if normalized_kind is None and normalized_direction is None:
        raise ValueError("external flow kind and direction are required")
    if normalized_kind is None:
        assert normalized_direction is not None
        normalized_kind = _kind_for_direction(normalized_direction)
    if normalized_direction is None:
        normalized_direction = normalized_kind.direction
    if normalized_kind.direction is not normalized_direction:
        raise ValueError("external flow kind and direction must describe the same movement")
    return normalized_kind, normalized_direction


def _require_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def _require_external_flow(session: Session, flow_id: int) -> ExternalFlow:
    flow = session.get(ExternalFlow, flow_id)
    if flow is None:
        raise ExternalFlowNotFoundError(f"external flow {flow_id} was not found")
    return flow


def _require_transfer_link(session: Session, link_id: int) -> ExternalTransferLink:
    link = session.get(ExternalTransferLink, link_id)
    if link is None:
        raise ExternalTransferLinkNotFoundError(f"external transfer link {link_id} was not found")
    return link


def _transfer_legs(session: Session, link_id: int) -> list[ExternalFlow]:
    return list(
        session.scalars(
            select(ExternalFlow)
            .where(ExternalFlow.transfer_link_id == link_id)
            .order_by(ExternalFlow.id)
        )
    )


def _is_complete_transfer(legs: list[ExternalFlow]) -> bool:
    if len(legs) != 2:
        return False
    first, second = legs
    return first.account_id != second.account_id and first.direction != second.direction


def _validate_transfer_legs(legs: list[ExternalFlow]) -> None:
    if len(legs) > 2:
        raise ValueError("an external transfer link may contain at most two legs")
    if len(legs) == 2 and not _is_complete_transfer(legs):
        raise ValueError("transfer link legs must use distinct accounts and opposite directions")


def _refresh_transfer_status(session: Session, link: ExternalTransferLink) -> list[ExternalFlow]:
    legs = _transfer_legs(session, link.id)
    _validate_transfer_legs(legs)
    link.status = (
        ExternalTransferStatus.RESOLVED.value
        if _is_complete_transfer(legs)
        else ExternalTransferStatus.UNRESOLVED.value
    )
    session.flush()
    return legs


def refresh_external_transfer_link_statuses(session: Session) -> None:
    """Reconcile persisted status after a bulk lifecycle operation.

    Reporting-month draft deletion removes child rows with a set-based SQL
    delete, so it cannot use the normal per-flow delete path.  Keeping this
    small explicit hook prevents a surviving owner link from retaining a stale
    ``resolved`` status after one or both legs are deleted.
    """

    links = list(session.scalars(select(ExternalTransferLink)))
    for link in links:
        _refresh_transfer_status(session, link)


def _require_editable_transfer_legs(session: Session, legs: Iterable[ExternalFlow]) -> None:
    for leg in legs:
        require_editable_child_month(session, leg)


def _validate_new_link_leg(
    session: Session,
    link: ExternalTransferLink,
    *,
    account_id: int,
    direction: ExternalFlowDirection,
    excluding_flow_id: int | None = None,
) -> list[ExternalFlow]:
    legs = [leg for leg in _transfer_legs(session, link.id) if leg.id != excluding_flow_id]
    _validate_transfer_legs(legs)
    if len(legs) == 2:
        raise ValueError("an external transfer link already has two legs")
    if legs and (legs[0].account_id == account_id or legs[0].direction == direction.value):
        raise ValueError("transfer link legs must use distinct accounts and opposite directions")
    return legs


def list_external_flows(
    session: Session,
    *,
    reporting_month_id: int | None = None,
    account_id: int | None = None,
    transfer_link_id: int | None = None,
) -> list[ExternalFlow]:
    statement = select(ExternalFlow)
    if reporting_month_id is not None:
        statement = statement.where(ExternalFlow.reporting_month_id == reporting_month_id)
    if account_id is not None:
        statement = statement.where(ExternalFlow.account_id == account_id)
    if transfer_link_id is not None:
        statement = statement.where(ExternalFlow.transfer_link_id == transfer_link_id)
    statement = statement.order_by(
        ExternalFlow.reporting_month_id,
        ExternalFlow.event_date,
        ExternalFlow.id,
    )
    return list(session.scalars(statement))


def get_external_flow(session: Session, flow_id: int) -> ExternalFlow:
    return _require_external_flow(session, flow_id)


def list_external_transfer_links(session: Session) -> list[ExternalTransferLink]:
    return list(
        session.scalars(
            select(ExternalTransferLink).order_by(
                ExternalTransferLink.created_at,
                ExternalTransferLink.id,
            )
        )
    )


def get_external_transfer_link(session: Session, link_id: int) -> ExternalTransferLink:
    return _require_transfer_link(session, link_id)


def transfer_link_legs(session: Session, link_id: int) -> list[ExternalFlow]:
    link = _require_transfer_link(session, link_id)
    return _transfer_legs(session, link.id)


def create_external_transfer_link(
    session: Session,
    *,
    transfer_key: str | None = None,
    flow_ids: Iterable[int] = (),
    notes: str | None = None,
) -> ExternalTransferLink:
    normalized_key = _normalize_text(
        transfer_key if transfer_key is not None else f"transfer-{uuid4().hex}",
        field="transfer_key",
        max_length=128,
    )
    ids = list(flow_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("flow_ids must not contain duplicates")
    if len(ids) > 2:
        raise ValueError("an external transfer link may contain at most two legs")

    flows = [_require_external_flow(session, flow_id) for flow_id in ids]
    _require_editable_transfer_legs(session, flows)
    if any(flow.transfer_link_id is not None for flow in flows):
        raise ValueError("an external flow is already attached to a transfer link")
    _validate_transfer_legs(flows)

    link = ExternalTransferLink(
        transfer_key=normalized_key,
        status=ExternalTransferStatus.UNRESOLVED.value,
        notes=notes,
    )
    session.add(link)
    session.flush()
    for flow in flows:
        flow.transfer_link_id = link.id
    session.flush()
    _refresh_transfer_status(session, link)
    session.commit()
    session.refresh(link)
    return link


def update_external_transfer_link(
    session: Session,
    link_id: int,
    *,
    transfer_key: str | None = None,
    notes: str | None = None,
) -> ExternalTransferLink:
    link = _require_transfer_link(session, link_id)
    if transfer_key is not None:
        link.transfer_key = _normalize_text(
            transfer_key,
            field="transfer_key",
            max_length=128,
        )
    if notes is not None:
        link.notes = notes
    session.commit()
    session.refresh(link)
    return link


def delete_external_transfer_link(session: Session, link_id: int) -> None:
    link = _require_transfer_link(session, link_id)
    if _transfer_legs(session, link.id):
        raise ValueError("transfer link must be empty before deletion")
    session.delete(link)
    session.commit()


def stage_create_external_flow(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    event_date: date,
    boundary_amount: RubleAmount | str,
    direction: ExternalFlowDirection | str,
    kind: ExternalFlowKind | str,
    scope_membership: ExternalFlowScopeMembership | str = ExternalFlowScopeMembership.UNKNOWN,
    transfer_link_id: int | None = None,
    currency: str = "RUB",
    source: str = "manual",
    notes: str | None = None,
) -> ExternalFlow:
    require_editable_reporting_month(session, reporting_month_id)
    _require_account(session, account_id)
    normalized_kind, normalized_direction = _normalize_kind_direction(kind, direction)
    normalized_scope_membership = _coerce_scope_membership(scope_membership)
    amount_kopecks = _normalize_exact_amount(boundary_amount, field="boundary_amount")
    normalized_currency = _normalize_currency(currency)
    normalized_source = _normalize_text(source, field="source", max_length=64)

    link = None
    if transfer_link_id is not None:
        link = _require_transfer_link(session, transfer_link_id)
        _validate_new_link_leg(
            session,
            link,
            account_id=account_id,
            direction=normalized_direction,
        )
        _require_editable_transfer_legs(session, _transfer_legs(session, link.id))

    flow = ExternalFlow(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        event_date=event_date,
        boundary_amount_kopecks=amount_kopecks,
        direction=normalized_direction.value,
        kind=normalized_kind.value,
        scope_membership=normalized_scope_membership.value,
        currency=normalized_currency,
        transfer_link_id=transfer_link_id,
        source=normalized_source,
        notes=notes,
    )
    session.add(flow)
    session.flush()
    if link is not None:
        _refresh_transfer_status(session, link)
    return flow


def create_external_flow(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    event_date: date,
    boundary_amount: RubleAmount | str,
    direction: ExternalFlowDirection | str,
    kind: ExternalFlowKind | str,
    scope_membership: ExternalFlowScopeMembership | str = ExternalFlowScopeMembership.UNKNOWN,
    transfer_link_id: int | None = None,
    currency: str = "RUB",
    source: str = "manual",
    notes: str | None = None,
) -> ExternalFlow:
    flow = stage_create_external_flow(
        session,
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        event_date=event_date,
        boundary_amount=boundary_amount,
        direction=direction,
        kind=kind,
        scope_membership=scope_membership,
        transfer_link_id=transfer_link_id,
        currency=currency,
        source=source,
        notes=notes,
    )
    session.commit()
    session.refresh(flow)
    return flow


def stage_update_external_flow(
    session: Session,
    flow_id: int,
    *,
    account_id: int | None = None,
    event_date: date | None = None,
    boundary_amount: RubleAmount | str | None = None,
    direction: ExternalFlowDirection | str | None = None,
    kind: ExternalFlowKind | str | None = None,
    scope_membership: ExternalFlowScopeMembership | str | None = None,
    transfer_link_id: int | None | object = _UNSET,
    currency: str | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> ExternalFlow:
    flow = _require_external_flow(session, flow_id)
    require_editable_child_month(session, flow)

    new_account_id = flow.account_id if account_id is None else account_id
    new_account = _require_account(session, new_account_id)
    current_kind = ExternalFlowKind(flow.kind)
    current_direction = ExternalFlowDirection(flow.direction)
    normalized_scope_membership = (
        _coerce_scope_membership(scope_membership) if scope_membership is not None else None
    )
    if kind is None and direction is None:
        normalized_kind, normalized_direction = current_kind, current_direction
    else:
        normalized_kind, normalized_direction = _normalize_kind_direction(kind, direction)

    new_link_id = flow.transfer_link_id
    link_changed = transfer_link_id is not _UNSET and transfer_link_id != flow.transfer_link_id
    if transfer_link_id is not _UNSET:
        new_link_id = transfer_link_id  # type: ignore[assignment]

    old_link = (
        _require_transfer_link(session, flow.transfer_link_id)
        if flow.transfer_link_id is not None
        else None
    )
    new_link = _require_transfer_link(session, new_link_id) if new_link_id is not None else None

    if old_link is not None and (
        link_changed or account_id is not None or direction is not None or kind is not None
    ):
        old_legs = _transfer_legs(session, old_link.id)
        _require_editable_transfer_legs(session, old_legs)
        if new_link is old_link:
            _validate_new_link_leg(
                session,
                old_link,
                account_id=new_account.id,
                direction=normalized_direction,
                excluding_flow_id=flow.id,
            )
    if new_link is not None and new_link is not old_link:
        new_legs = _validate_new_link_leg(
            session,
            new_link,
            account_id=new_account.id,
            direction=normalized_direction,
        )
        _require_editable_transfer_legs(session, new_legs)

    identity_changed = new_account_id != flow.account_id or (
        event_date is not None and event_date != flow.event_date
    )
    if account_id is not None:
        flow.account_id = new_account.id
    if event_date is not None:
        flow.event_date = event_date
    if boundary_amount is not None:
        flow.boundary_amount_kopecks = _normalize_exact_amount(
            boundary_amount, field="boundary_amount"
        )
    if kind is not None or direction is not None:
        flow.kind = normalized_kind.value
        flow.direction = normalized_direction.value
    if normalized_scope_membership is not None:
        flow.scope_membership = normalized_scope_membership.value
    elif identity_changed:
        flow.scope_membership = ExternalFlowScopeMembership.UNKNOWN.value
    if transfer_link_id is not _UNSET:
        flow.transfer_link_id = new_link_id  # type: ignore[assignment]
    if currency is not None:
        flow.currency = _normalize_currency(currency)
    if source is not None:
        flow.source = _normalize_text(source, field="source", max_length=64)
    if notes is not None:
        flow.notes = notes

    session.flush()
    if old_link is not None and (
        link_changed or account_id is not None or direction is not None or kind is not None
    ):
        _refresh_transfer_status(session, old_link)
    if new_link is not None and new_link is not old_link:
        _refresh_transfer_status(session, new_link)
    return flow


def update_external_flow(
    session: Session,
    flow_id: int,
    *,
    account_id: int | None = None,
    event_date: date | None = None,
    boundary_amount: RubleAmount | str | None = None,
    direction: ExternalFlowDirection | str | None = None,
    kind: ExternalFlowKind | str | None = None,
    scope_membership: ExternalFlowScopeMembership | str | None = None,
    transfer_link_id: int | None | object = _UNSET,
    currency: str | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> ExternalFlow:
    flow = stage_update_external_flow(
        session,
        flow_id,
        account_id=account_id,
        event_date=event_date,
        boundary_amount=boundary_amount,
        direction=direction,
        kind=kind,
        scope_membership=scope_membership,
        transfer_link_id=transfer_link_id,
        currency=currency,
        source=source,
        notes=notes,
    )
    session.commit()
    session.refresh(flow)
    return flow


def delete_external_flow(session: Session, flow_id: int) -> None:
    flow = _require_external_flow(session, flow_id)
    require_editable_child_month(session, flow)
    link = _require_transfer_link(session, flow.transfer_link_id) if flow.transfer_link_id else None
    if link is not None:
        _require_editable_transfer_legs(session, _transfer_legs(session, link.id))
    session.delete(flow)
    session.flush()
    if link is not None:
        _refresh_transfer_status(session, link)
    session.commit()


def classify_external_flow(
    session: Session,
    flow_id: int,
    *,
    scope: ExternalFlowScope | str,
    account_id: int | None = None,
) -> ExternalFlowClassification:
    """Classify one explicit flow at portfolio or account scope.

    ``scope_membership`` is an owner-asserted, persisted v1 constraint for the
    historical flow.  ``unknown`` is explicitly non-authoritative.  The
    account's current ``include_in_returns`` flag is never used to reinterpret
    a historical flow, and this helper does not claim interval coverage;
    R08-01B/C must add that contract before exact performance metrics consume it.
    """

    flow = _require_external_flow(session, flow_id)
    try:
        normalized_scope = ExternalFlowScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported external flow scope: {scope!r}") from error

    if normalized_scope is ExternalFlowScope.ACCOUNT:
        if account_id is None:
            raise ValueError("account_id is required for account scope")
        _require_account(session, account_id)
        if flow.account_id != account_id:
            return ExternalFlowClassification.NOT_IN_SCOPE
        if flow.transfer_link_id is not None:
            link = _require_transfer_link(session, flow.transfer_link_id)
            legs = _transfer_legs(session, link.id)
            if not _is_complete_transfer(legs):
                return ExternalFlowClassification.UNRESOLVED
        if flow.scope_membership == ExternalFlowScopeMembership.UNKNOWN.value:
            return ExternalFlowClassification.NOT_AUTHORITATIVE
        if flow.scope_membership == ExternalFlowScopeMembership.STABLE_IN_SCOPE.value:
            return ExternalFlowClassification(flow.kind)
        return ExternalFlowClassification.NOT_IN_SCOPE

    if flow.scope_membership == ExternalFlowScopeMembership.STABLE_OUT_OF_SCOPE.value:
        return ExternalFlowClassification.NOT_IN_SCOPE
    if flow.transfer_link_id is None:
        if flow.scope_membership == ExternalFlowScopeMembership.UNKNOWN.value:
            return ExternalFlowClassification.NOT_AUTHORITATIVE
        return ExternalFlowClassification(flow.kind)

    link = _require_transfer_link(session, flow.transfer_link_id)
    legs = _transfer_legs(session, link.id)
    if not _is_complete_transfer(legs):
        return ExternalFlowClassification.UNRESOLVED
    if flow.scope_membership == ExternalFlowScopeMembership.UNKNOWN.value:
        return ExternalFlowClassification.NOT_AUTHORITATIVE
    other = next(leg for leg in legs if leg.id != flow.id)
    if other.scope_membership == ExternalFlowScopeMembership.UNKNOWN.value:
        return ExternalFlowClassification.NOT_AUTHORITATIVE
    if other.scope_membership == ExternalFlowScopeMembership.STABLE_IN_SCOPE.value:
        return ExternalFlowClassification.INTERNAL_TRANSFER
    return ExternalFlowClassification(flow.kind)


def external_flow_transfer_status(
    session: Session, flow: ExternalFlow
) -> ExternalTransferStatus | None:
    if flow.transfer_link_id is None:
        return None
    link = _require_transfer_link(session, flow.transfer_link_id)
    legs = _transfer_legs(session, link.id)
    return (
        ExternalTransferStatus.RESOLVED
        if _is_complete_transfer(legs)
        else ExternalTransferStatus.UNRESOLVED
    )


# The shorter names are the public vocabulary used by the API/task card.
create_transfer_link = create_external_transfer_link
update_transfer_link = update_external_transfer_link
delete_transfer_link = delete_external_transfer_link
list_transfer_links = list_external_transfer_links
get_transfer_link = get_external_transfer_link
