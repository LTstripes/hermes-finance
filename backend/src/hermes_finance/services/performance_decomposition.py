"""Read-only PERF04C account and internal-transfer decomposition."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import (
    AccountPerformanceComponent,
    AvailabilityReasonCode,
    ExternalFlowClassification,
    ExternalFlowScope,
    ExternalTransferReconciliationKind,
    InternalTransferEffect,
    Perf04cDecompositionResult,
    PerformanceAttributionQuality,
    PerformanceAttributionResult,
    PerformanceAvailabilityStatus,
    PerformanceScope,
    RubleAmount,
    TransferReconciliationEvidence,
)
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    ExternalFlow,
)
from hermes_finance.services.external_flows import classify_external_flow
from hermes_finance.services.performance_attribution import (
    performance_attribution_for_interval,
)
from hermes_finance.services.transfer_reconciliation import (
    iter_transfer_reconciliation_evidence,
)

PERF04C_CONTRACT = "PERF04C"
PERF04C_CONTRACT_VERSION = 1
PERF04C_METRIC = "value_change_after_external_flows_decomposition"

_RECONCILIATION_KINDS = frozenset(kind.value for kind in ExternalTransferReconciliationKind)
_RECONCILIATION_COST_KINDS = frozenset(
    {
        ExternalTransferReconciliationKind.INTERNAL_FEE.value,
        ExternalTransferReconciliationKind.INTERNAL_COMMISSION.value,
        ExternalTransferReconciliationKind.INTERNAL_TAX.value,
    }
)


@dataclass(frozen=True, slots=True)
class _TransferPair:
    link_id: int
    source: ExternalFlow
    destination: ExternalFlow


def _normalise_currency(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _membership_at(
    rows: Iterable[AccountPerformanceScopeMembership], observed_date: date
) -> bool | None:
    matches = [
        row
        for row in rows
        if row.effective_from <= observed_date
        and (row.effective_to is None or row.effective_to >= observed_date)
    ]
    if len(matches) != 1:
        return None
    return matches[0].include_in_returns


def _membership_rows(
    session: Session, account_ids: Iterable[int]
) -> dict[int, tuple[AccountPerformanceScopeMembership, ...]]:
    ids = tuple(sorted(set(account_ids)))
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]] = {
        account_id: [] for account_id in ids
    }
    if not ids:
        return {account_id: tuple(rows) for account_id, rows in rows_by_account.items()}
    rows = session.scalars(
        select(AccountPerformanceScopeMembership)
        .where(AccountPerformanceScopeMembership.account_id.in_(ids))
        .order_by(
            AccountPerformanceScopeMembership.account_id,
            AccountPerformanceScopeMembership.effective_from,
            AccountPerformanceScopeMembership.id,
        )
    )
    for row in rows:
        rows_by_account[row.account_id].append(row)
    return {account_id: tuple(rows) for account_id, rows in rows_by_account.items()}


def _historically_in_scope_accounts(
    session: Session,
    *,
    parent: PerformanceAttributionResult,
) -> tuple[tuple[int, ...], set[str], dict[int, tuple[AccountPerformanceScopeMembership, ...]]]:
    prerequisites = parent.bridge_prerequisites
    if prerequisites is None:
        return (), {AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value}, {}

    all_account_ids = tuple(sorted(prerequisites.scope_membership.account_ids))
    rows_by_account = _membership_rows(session, all_account_ids)
    account_ids: list[int] = []
    reasons: set[str] = set()
    for account_id in all_account_ids:
        rows = rows_by_account.get(account_id, ())
        opening_membership = _membership_at(rows, parent.start_date)
        closing_membership = _membership_at(rows, parent.end_date)
        if opening_membership is None or closing_membership is None:
            reasons.add(AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)
            continue
        # A stable out-of-scope account is part of R08's historical universe,
        # but it is not an account component of this selected portfolio.
        if opening_membership and closing_membership:
            account_ids.append(account_id)
    if not account_ids:
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
    return tuple(account_ids), reasons, rows_by_account


def _bridge_identity_holds(result: PerformanceAttributionResult) -> bool:
    if (
        not result.is_available
        or result.opening_value is None
        or result.closing_value is None
        or result.value is None
        or result.external_flow_summary.signed_total is None
    ):
        return False
    return (
        result.opening_value.kopecks
        + result.external_flow_summary.signed_total.kopecks
        + result.value.kopecks
        == result.closing_value.kopecks
    )


def _result(
    parent: PerformanceAttributionResult,
    *,
    reasons: Iterable[str] = (),
    value: RubleAmount | None = None,
    account_components: Iterable[AccountPerformanceComponent] = (),
    internal_transfer_effects: Iterable[InternalTransferEffect] = (),
) -> Perf04cDecompositionResult:
    reason_codes = set(parent.reason_codes)
    reason_codes.update(reasons)
    is_available = parent.is_available and value is not None and not reason_codes
    return Perf04cDecompositionResult(
        scope=parent.scope,
        account_id=parent.account_id,
        start_date=parent.start_date,
        end_date=parent.end_date,
        performance_currency=parent.performance_currency,
        availability=(
            PerformanceAvailabilityStatus.AVAILABLE
            if is_available
            else PerformanceAvailabilityStatus.NOT_COMPUTABLE
        ),
        quality=(
            PerformanceAttributionQuality.EXACT
            if is_available
            else PerformanceAttributionQuality.UNAVAILABLE
        ),
        parent_value=parent.value,
        value=value if is_available else None,
        account_components=(tuple(account_components) if is_available else ()),
        internal_transfer_effects=(tuple(internal_transfer_effects) if is_available else ()),
        parent_opening_value=parent.opening_value,
        parent_closing_value=parent.closing_value,
        parent_external_flow_summary=parent.external_flow_summary,
        evidence=parent.evidence,
        reason_codes=tuple(sorted(reason_codes)),
    )


def _account_components(
    session: Session,
    *,
    parent: PerformanceAttributionResult,
    account_ids: tuple[int, ...],
) -> tuple[tuple[AccountPerformanceComponent, ...], set[str]]:
    components: list[AccountPerformanceComponent] = []
    reasons: set[str] = set()
    for account_id in account_ids:
        result = performance_attribution_for_interval(
            session,
            start_date=parent.start_date,
            end_date=parent.end_date,
            scope=PerformanceScope.ACCOUNT,
            account_id=account_id,
        )
        if (
            not result.is_available
            or result.scope is not PerformanceScope.ACCOUNT
            or result.account_id != account_id
            or result.performance_currency != parent.performance_currency
            or result.opening_value is None
            or result.closing_value is None
            or result.value is None
            or result.external_flow_summary.signed_total is None
        ):
            reasons.update(result.reason_codes)
            if not result.reason_codes:
                reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
            continue
        if not _bridge_identity_holds(result):
            reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
            continue
        components.append(
            AccountPerformanceComponent(
                account_id=account_id,
                opening_value=result.opening_value,
                closing_value=result.closing_value,
                external_flow_summary=result.external_flow_summary,
                value=result.value,
            )
        )
    return tuple(components), reasons


def _transfer_pairs(
    session: Session,
    *,
    parent: PerformanceAttributionResult,
    account_ids: tuple[int, ...],
    rows_by_account: dict[int, tuple[AccountPerformanceScopeMembership, ...]],
) -> tuple[tuple[_TransferPair, ...], set[str]]:
    rows = session.scalars(
        select(ExternalFlow)
        .where(ExternalFlow.transfer_link_id.is_not(None))
        .order_by(ExternalFlow.transfer_link_id, ExternalFlow.id)
    )
    legs_by_link: dict[int, list[ExternalFlow]] = defaultdict(list)
    for row in rows:
        assert row.transfer_link_id is not None
        legs_by_link[row.transfer_link_id].append(row)

    account_id_set = set(account_ids)
    pairs: list[_TransferPair] = []
    reasons: set[str] = set()
    for link_id in sorted(legs_by_link):
        legs = legs_by_link[link_id]
        if not any(parent.start_date <= leg.event_date <= parent.end_date for leg in legs):
            continue
        if len(legs) != 2:
            reasons.add(AvailabilityReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)
            continue

        source_legs = [leg for leg in legs if leg.direction == "withdrawal"]
        destination_legs = [leg for leg in legs if leg.direction == "contribution"]
        if (
            len(source_legs) != 1
            or len(destination_legs) != 1
            or source_legs[0].account_id == destination_legs[0].account_id
        ):
            reasons.add(AvailabilityReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)
            continue
        source = source_legs[0]
        destination = destination_legs[0]

        try:
            classifications = tuple(
                classify_external_flow(
                    session,
                    leg.id,
                    scope=ExternalFlowScope.PORTFOLIO,
                )
                for leg in legs
            )
        except (LookupError, ValueError):
            reasons.add(AvailabilityReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)
            continue
        # A transfer crossing the selected portfolio boundary remains an
        # external flow and deliberately produces no internal effect row.
        if any(
            classification is not ExternalFlowClassification.INTERNAL_TRANSFER
            for classification in classifications
        ):
            continue

        if source.account_id not in account_id_set or destination.account_id not in account_id_set:
            reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
            continue
        if (
            _membership_at(rows_by_account.get(source.account_id, ()), source.event_date)
            is not True
            or _membership_at(
                rows_by_account.get(destination.account_id, ()), destination.event_date
            )
            is not True
        ):
            reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
            continue
        if not (
            parent.start_date <= source.event_date <= parent.end_date
            and parent.start_date <= destination.event_date <= parent.end_date
        ):
            # An available parent should not need a synthesized boundary term
            # for a transfer whose transit crosses the requested interval.
            reasons.add(AvailabilityReasonCode.TRANSFER_IN_TRANSIT_UNVALUED.value)
            continue
        pairs.append(_TransferPair(link_id=link_id, source=source, destination=destination))
    return tuple(pairs), reasons


def _transfer_effect(
    pair: _TransferPair,
    *,
    evidence: tuple[object, ...],
    performance_currency: str,
) -> tuple[InternalTransferEffect | None, set[str]]:
    reasons: set[str] = set()
    safe_evidence: list[TransferReconciliationEvidence] = []
    evidence_ids: set[int] = set()
    for item in evidence:
        item_id = getattr(item, "id", None)
        kind = getattr(item, "kind", None)
        amount = _nonnegative_int(getattr(item, "amount_kopecks", None))
        currency = _normalise_currency(getattr(item, "currency", None))
        if (
            isinstance(item_id, bool)
            or not isinstance(item_id, int)
            or item_id in evidence_ids
            or kind not in _RECONCILIATION_KINDS
            or amount is None
            or len(currency) != 3
        ):
            reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)
            continue
        evidence_ids.add(item_id)
        safe_evidence.append(
            TransferReconciliationEvidence(
                id=item_id,
                kind=kind,
                amount=RubleAmount(amount),
                currency=currency,
            )
        )

    source_amount = _nonnegative_int(pair.source.boundary_amount_kopecks)
    destination_amount = _nonnegative_int(pair.destination.boundary_amount_kopecks)
    source_currency = _normalise_currency(pair.source.currency)
    destination_currency = _normalise_currency(pair.destination.currency)
    if source_amount is None or destination_amount is None:
        reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)
    if (
        not source_currency
        or source_currency != destination_currency
        or source_currency != performance_currency
    ):
        reasons.add(AvailabilityReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)
    if safe_evidence and any(item.currency != source_currency for item in safe_evidence):
        reasons.add(AvailabilityReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)

    if not reasons and source_amount is not None and destination_amount is not None:
        if source_amount == destination_amount:
            effect_kopecks = 0
        elif destination_amount > source_amount:
            reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)
            effect_kopecks = 0
        else:
            difference = source_amount - destination_amount
            cost_evidence = [
                item for item in safe_evidence if item.kind in _RECONCILIATION_COST_KINDS
            ]
            if not cost_evidence or any(item.currency != source_currency for item in cost_evidence):
                reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)
                effect_kopecks = 0
            elif sum(item.amount.kopecks for item in cost_evidence) != difference:
                reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)
                effect_kopecks = 0
            else:
                effect_kopecks = destination_amount - source_amount
    else:
        effect_kopecks = 0

    if reasons:
        return None, reasons
    assert source_amount is not None
    assert destination_amount is not None
    return (
        InternalTransferEffect(
            transfer_link_id=pair.link_id,
            source_flow_id=pair.source.id,
            destination_flow_id=pair.destination.id,
            source_account_id=pair.source.account_id,
            destination_account_id=pair.destination.account_id,
            source_date=pair.source.event_date,
            destination_date=pair.destination.event_date,
            source_amount=RubleAmount(source_amount),
            destination_amount=RubleAmount(destination_amount),
            effect=RubleAmount(effect_kopecks),
            reconciliation_evidence=tuple(sorted(safe_evidence, key=lambda item: item.id)),
        ),
        reasons,
    )


def _transfer_effects(
    session: Session,
    *,
    pairs: tuple[_TransferPair, ...],
    performance_currency: str,
) -> tuple[tuple[InternalTransferEffect, ...], set[str]]:
    evidence_by_link = iter_transfer_reconciliation_evidence(
        session, (pair.link_id for pair in pairs)
    )
    evidence_owner_by_id: dict[int, int] = {}
    effects: list[InternalTransferEffect] = []
    reasons: set[str] = set()
    for pair in pairs:
        evidence = evidence_by_link.get(pair.link_id, ())
        for item in evidence:
            item_id = getattr(item, "id", None)
            if isinstance(item_id, int) and not isinstance(item_id, bool):
                previous_link_id = evidence_owner_by_id.setdefault(item_id, pair.link_id)
                if previous_link_id != pair.link_id:
                    reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)
        effect, effect_reasons = _transfer_effect(
            pair,
            evidence=evidence,
            performance_currency=performance_currency,
        )
        reasons.update(effect_reasons)
        if effect is not None:
            effects.append(effect)
    return tuple(effects), reasons


@coherent_read_operation
def performance_decomposition_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> Perf04cDecompositionResult:
    """Return a complete exact PERF04C portfolio decomposition or null rows."""

    try:
        normalized_scope = PerformanceScope(scope)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unsupported performance scope: {scope!r}") from error
    if normalized_scope is not PerformanceScope.PORTFOLIO or account_id is not None:
        raise ValueError("PERF04C decomposition supports portfolio scope only")

    parent = performance_attribution_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=PerformanceScope.PORTFOLIO,
    )
    if not parent.is_available or parent.value is None:
        return _result(parent, reasons=parent.reason_codes)

    reasons: set[str] = set()
    if not _bridge_identity_holds(parent):
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    account_ids, account_reasons, rows_by_account = _historically_in_scope_accounts(
        session,
        parent=parent,
    )
    reasons.update(account_reasons)
    if reasons:
        return _result(parent, reasons=reasons)

    account_components, account_component_reasons = _account_components(
        session,
        parent=parent,
        account_ids=account_ids,
    )
    reasons.update(account_component_reasons)
    if len(account_components) != len(account_ids):
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    pairs, pair_reasons = _transfer_pairs(
        session,
        parent=parent,
        account_ids=account_ids,
        rows_by_account=rows_by_account,
    )
    reasons.update(pair_reasons)
    transfer_effects, transfer_reasons = _transfer_effects(
        session,
        pairs=pairs,
        performance_currency=parent.performance_currency,
    )
    reasons.update(transfer_reasons)

    if reasons:
        return _result(parent, reasons=reasons)

    assert parent.external_flow_summary.signed_total is not None
    account_opening = sum(component.opening_value.kopecks for component in account_components)
    account_closing = sum(component.closing_value.kopecks for component in account_components)
    if (
        parent.opening_value is None
        or parent.closing_value is None
        or account_opening != parent.opening_value.kopecks
        or account_closing != parent.closing_value.kopecks
    ):
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    transfer_delta = sum(
        effect.destination_amount.kopecks - effect.source_amount.kopecks
        for effect in transfer_effects
    )
    account_flow_total = sum(
        component.external_flow_summary.signed_total.kopecks
        for component in account_components
        if component.external_flow_summary.signed_total is not None
    )
    if account_flow_total != parent.external_flow_summary.signed_total.kopecks + transfer_delta:
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    account_bridge_total = sum(component.value.kopecks for component in account_components)
    transfer_effect_total = sum(effect.effect.kopecks for effect in transfer_effects)
    if parent.value.kopecks != account_bridge_total + transfer_effect_total:
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    if reasons:
        return _result(parent, reasons=reasons)
    return _result(
        parent,
        value=parent.value,
        account_components=account_components,
        internal_transfer_effects=transfer_effects,
    )


# Discoverable aliases keep the read-model function easy to locate for
# downstream backend consumers without exposing an API or creating a new metric.
performance_component_decomposition_for_interval = performance_decomposition_for_interval
performance_component_attribution_for_interval = performance_decomposition_for_interval
component_attribution_for_interval = performance_decomposition_for_interval
perf04c_decomposition_for_interval = performance_decomposition_for_interval
account_transfer_decomposition_for_interval = performance_decomposition_for_interval


__all__ = [
    "PERF04C_CONTRACT",
    "PERF04C_CONTRACT_VERSION",
    "PERF04C_METRIC",
    "account_transfer_decomposition_for_interval",
    "component_attribution_for_interval",
    "perf04c_decomposition_for_interval",
    "performance_component_attribution_for_interval",
    "performance_component_decomposition_for_interval",
    "performance_decomposition_for_interval",
]
