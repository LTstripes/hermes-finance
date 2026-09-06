"""Framework-independent DTOs and arithmetic for R07-06A.

This module deliberately models support state separately from concentration.
``unavailable`` and ``unknown`` are data-quality outcomes, never risk scores
or recommendations. Percentages use ``Decimal`` and ``ROUND_HALF_UP`` via the
existing financial value contract.

Pure canonical projection builder lives here (R1): both Risk and Scenario Lab
must call the same builder for allocation buckets. Buckets are distinct per
R07-06A: stock/bond/fund/currency/gold/other distinct + unknown_asset_class,
unassigned_cash, denominator liquid_assets. No gold_other alias.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount

_PERCENT_SCALE = Decimal("0.01")

VALID_ASSET_TYPES: frozenset[str] = frozenset(
    {"stock", "bond", "fund", "currency", "gold", "other"}
)


class RiskSupportStatus(StrEnum):
    SUPPORTED = "supported"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MetricSupport:
    status: RiskSupportStatus
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SupportIssue:
    source_kind: str
    source_id: int | None
    support: MetricSupport


@dataclass(frozen=True, slots=True)
class AllocationSlice:
    key: str
    label: str
    amount: RubleAmount
    share_pct: Decimal | None
    account_id: int | None = None
    instrument_id: int | None = None
    instrument_type: str | None = None


@dataclass(frozen=True, slots=True)
class AllocationMetric:
    support: MetricSupport
    denominator: RubleAmount
    covered_amount: RubleAmount
    unallocated_amount: RubleAmount
    coverage_pct: Decimal | None
    items: tuple[AllocationSlice, ...]
    excluded: tuple[SupportIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ConcentrationItem:
    key: str
    label: str
    amount: RubleAmount
    share_pct: Decimal | None
    account_id: int | None = None
    account_name: str | None = None
    instrument_id: int | None = None
    instrument_name: str | None = None
    instrument_type: str | None = None
    position_id: int | None = None
    event_count: int | None = None
    is_approximate: bool = False


@dataclass(frozen=True, slots=True)
class ConcentrationMetric:
    support: MetricSupport
    denominator: RubleAmount
    top_n: int
    top_amount: RubleAmount
    top_share_pct: Decimal | None
    items: tuple[ConcentrationItem, ...]
    excluded: tuple[SupportIssue, ...] = ()
    is_approximate: bool = False


@dataclass(frozen=True, slots=True)
class RiskAllocationResult:
    reporting_month_id: int
    as_of_date: date
    base_currency: str
    liquid_assets_total: RubleAmount
    allocation_by_asset_class: AllocationMetric
    allocation_by_account: AllocationMetric
    top_positions: ConcentrationMetric
    payout_concentration: ConcentrationMetric
    redemption_concentration: ConcentrationMetric
    support: dict[str, MetricSupport]


# ---- immutable input DTOs for pure canonical builder (R1) ----


@dataclass(frozen=True, slots=True)
class RiskPositionInput:
    position_id: int
    account_id: int
    instrument_id: int
    instrument_type: str | None
    amount_kopecks: int


@dataclass(frozen=True, slots=True)
class RiskDepositInput:
    account_id: int
    amount_kopecks: int


@dataclass(frozen=True, slots=True)
class RiskAllocationInputs:
    cash_kopecks: int
    deposits: tuple[RiskDepositInput, ...]
    positions: tuple[RiskPositionInput, ...]
    liquid_assets_kopecks: int
    top_n: int


def percentage(amount_kopecks: int, denominator_kopecks: int) -> Decimal | None:
    """Return a two-decimal percentage, or ``None`` for a zero denominator."""
    if denominator_kopecks <= 0:
        return None
    return (Decimal(amount_kopecks) / Decimal(denominator_kopecks) * Decimal(100)).quantize(
        _PERCENT_SCALE, rounding=FINANCIAL_ROUNDING
    )


def support_from_issues(
    issues: Iterable[SupportIssue],
    *,
    extra_reason_codes: Iterable[str] = (),
) -> MetricSupport:
    """Collapse row-level issues into one deterministic metric state."""
    issues = tuple(issues)
    statuses = {issue.support.status for issue in issues}
    if RiskSupportStatus.UNAVAILABLE in statuses:
        status = RiskSupportStatus.UNAVAILABLE
    elif RiskSupportStatus.UNKNOWN in statuses:
        status = RiskSupportStatus.UNKNOWN
    else:
        status = RiskSupportStatus.SUPPORTED
    reasons = {reason for issue in issues for reason in issue.support.reason_codes}
    reasons.update(extra_reason_codes)
    return MetricSupport(status=status, reason_codes=tuple(sorted(reasons)))


def _money(kopecks: int) -> RubleAmount:
    return RubleAmount(kopecks)


def _allocation_metric(
    amounts: dict[str, int],
    *,
    denominator_kopecks: int,
    covered_kopecks: int,
    unallocated_kopecks: int,
    support: MetricSupport,
    excluded: tuple[SupportIssue, ...],
    account_ids: dict[str, int] | None = None,
    labels: dict[str, str] | None = None,
    instrument_types: dict[str, str] | None = None,
) -> AllocationMetric:
    slices: list[AllocationSlice] = []
    for key, amount in sorted(amounts.items(), key=lambda item: (-item[1], item[0])):
        if amount == 0:
            continue
        slices.append(
            AllocationSlice(
                key=key,
                label=labels.get(key, key) if labels is not None else key,
                amount=_money(amount),
                share_pct=percentage(amount, denominator_kopecks),
                account_id=account_ids.get(key) if account_ids is not None else None,
                instrument_type=(
                    instrument_types.get(key) if instrument_types is not None else None
                ),
            )
        )
    return AllocationMetric(
        support=support,
        denominator=_money(denominator_kopecks),
        covered_amount=_money(covered_kopecks),
        unallocated_amount=_money(unallocated_kopecks),
        coverage_pct=percentage(covered_kopecks, denominator_kopecks),
        items=tuple(slices),
        excluded=excluded,
    )


def _concentration_metric(
    items: list[ConcentrationItem],
    *,
    denominator_kopecks: int,
    top_n: int,
    issues: tuple[SupportIssue, ...],
    extra_reason_codes: tuple[str, ...] = (),
    is_approximate: bool = False,
) -> ConcentrationMetric:
    ordered = sorted(items, key=lambda item: (-item.amount.kopecks, item.key))
    selected = ordered[:top_n]
    selected_amount = sum(item.amount.kopecks for item in selected)
    with_shares = tuple(
        replace(item, share_pct=percentage(item.amount.kopecks, denominator_kopecks))
        for item in selected
    )
    return ConcentrationMetric(
        support=support_from_issues(issues, extra_reason_codes=extra_reason_codes),
        denominator=_money(denominator_kopecks),
        top_n=top_n,
        top_amount=_money(selected_amount),
        top_share_pct=percentage(selected_amount, denominator_kopecks),
        items=with_shares,
        excluded=issues,
        is_approximate=is_approximate,
    )


# ---- Pure canonical builder (R1): shared by risk_allocation and scenario_lab ----


def _valid_asset_type(itype: str | None) -> str | None:
    if isinstance(itype, str) and itype in VALID_ASSET_TYPES:
        return itype
    return None


def build_asset_allocation(
    *,
    cash_kopecks: int,
    deposits: tuple[RiskDepositInput, ...],
    positions: tuple[RiskPositionInput, ...],
    liquid_assets_kopecks: int,
    support: MetricSupport,
    excluded: tuple[SupportIssue, ...],
) -> AllocationMetric:
    """Pure builder for asset-class allocation per R07-06A.

    Buckets: cash, deposits, each VALID_ASSET_TYPES distinct, unknown_asset_class.
    Denominator is liquid_assets. No gold_other alias.
    """
    asset_amounts: dict[str, int] = defaultdict(int)
    unknown_kopecks = 0
    if cash_kopecks:
        asset_amounts["cash"] = cash_kopecks
    deposits_total = sum(d.amount_kopecks for d in deposits)
    if deposits_total:
        asset_amounts["deposits"] = deposits_total
    for pos in positions:
        kind = _valid_asset_type(pos.instrument_type)
        if kind is not None:
            asset_amounts[kind] += pos.amount_kopecks
        else:
            unknown_kopecks += pos.amount_kopecks
    known_total = sum(asset_amounts.values())
    amounts_for_metric = dict(asset_amounts)
    if unknown_kopecks:
        amounts_for_metric["unknown_asset_class"] = unknown_kopecks
    # instrument_types mapping for known types: type value -> type value
    instrument_types = {k: k for k in VALID_ASSET_TYPES}
    labels = {"unknown_asset_class": "Unknown asset class"}
    return _allocation_metric(
        amounts_for_metric,
        denominator_kopecks=liquid_assets_kopecks,
        covered_kopecks=known_total,
        unallocated_kopecks=unknown_kopecks,
        support=support,
        excluded=excluded,
        instrument_types=instrument_types,
        labels=labels,
    )


def build_account_allocation(
    *,
    cash_kopecks: int,
    deposits: tuple[RiskDepositInput, ...],
    positions: tuple[RiskPositionInput, ...],
    liquid_assets_kopecks: int,
    support: MetricSupport,
    excluded: tuple[SupportIssue, ...],
    account_names: dict[int, str] | None = None,
) -> AllocationMetric:
    """Pure builder for account allocation. Uses unassigned_cash for cash."""
    account_amounts: dict[int, int] = defaultdict(int)
    for dep in deposits:
        account_amounts[dep.account_id] += dep.amount_kopecks
    for pos in positions:
        account_amounts[pos.account_id] += pos.amount_kopecks
    covered = sum(account_amounts.values())
    amounts: dict[str, int] = {f"account:{aid}": amt for aid, amt in account_amounts.items()}
    if cash_kopecks:
        amounts["unassigned_cash"] = cash_kopecks
    labels: dict[str, str] = {}
    account_ids: dict[str, int] = {}
    for aid, name in (account_names or {}).items():
        key = f"account:{aid}"
        if key in amounts:
            labels[key] = name
            account_ids[key] = aid
    # Ensure account_ids for all account keys even without name mapping
    for aid in account_amounts:
        key = f"account:{aid}"
        if key not in account_ids:
            account_ids[key] = aid
    if "unassigned_cash" in amounts:
        labels["unassigned_cash"] = "Unassigned cash"
    # Fill missing labels with key itself handled in _allocation_metric
    return _allocation_metric(
        amounts,
        denominator_kopecks=liquid_assets_kopecks,
        covered_kopecks=covered,
        unallocated_kopecks=cash_kopecks,
        support=support,
        excluded=excluded,
        account_ids=account_ids,
        labels=labels,
    )


def build_top_positions(
    *,
    positions: tuple[RiskPositionInput, ...],
    liquid_assets_kopecks: int,
    top_n: int,
    issues: tuple[SupportIssue, ...],
    account_names: dict[int, str] | None = None,
    instrument_names: dict[int, str] | None = None,
) -> ConcentrationMetric:
    """Pure builder for top-N positions concentration."""
    items: list[ConcentrationItem] = []
    for pos in positions:
        if pos.amount_kopecks <= 0:
            continue
        # For R4, normative metric must keep only ids; names are optional presentation_metadata
        # Build item with ids; populate label as key but keep name fields if maps provided for backward compat?
        # To satisfy R4 remove names from normative, we exclude account_name/instrument_name from item when not needed.
        # Caller decides: if account_names/instrument_names not provided, names stay None.
        acc_name = (account_names or {}).get(pos.account_id) if account_names is not None else None
        inst_name = (
            (instrument_names or {}).get(pos.instrument_id)
            if instrument_names is not None
            else None
        )
        label = (
            f"{acc_name} / {inst_name}" if acc_name and inst_name else f"position:{pos.position_id}"
        )
        if acc_name and not inst_name:
            label = f"{acc_name} / instrument {pos.instrument_id}"
        elif inst_name and not acc_name:
            label = f"account {pos.account_id} / {inst_name}"
        items.append(
            ConcentrationItem(
                key=f"position:{pos.position_id}",
                label=label,
                amount=_money(pos.amount_kopecks),
                share_pct=None,
                account_id=pos.account_id,
                account_name=acc_name,
                instrument_id=pos.instrument_id,
                instrument_name=inst_name,
                instrument_type=pos.instrument_type
                if pos.instrument_type in VALID_ASSET_TYPES
                else None,
                position_id=pos.position_id,
            )
        )
    return _concentration_metric(
        items,
        denominator_kopecks=liquid_assets_kopecks,
        top_n=top_n,
        issues=issues,
    )


def build_risk_projection(
    inputs: RiskAllocationInputs,
    *,
    asset_support: MetricSupport,
    asset_excluded: tuple[SupportIssue, ...],
    account_support: MetricSupport,
    account_excluded: tuple[SupportIssue, ...],
    top_issues: tuple[SupportIssue, ...],
    account_names: dict[int, str] | None = None,
    instrument_names: dict[int, str] | None = None,
) -> tuple[AllocationMetric, AllocationMetric, ConcentrationMetric]:
    """Composite pure builder returning (asset, account, top_positions)."""
    asset = build_asset_allocation(
        cash_kopecks=inputs.cash_kopecks,
        deposits=inputs.deposits,
        positions=inputs.positions,
        liquid_assets_kopecks=inputs.liquid_assets_kopecks,
        support=asset_support,
        excluded=asset_excluded,
    )
    account = build_account_allocation(
        cash_kopecks=inputs.cash_kopecks,
        deposits=inputs.deposits,
        positions=inputs.positions,
        liquid_assets_kopecks=inputs.liquid_assets_kopecks,
        support=account_support,
        excluded=account_excluded,
        account_names=account_names,
    )
    top = build_top_positions(
        positions=inputs.positions,
        liquid_assets_kopecks=inputs.liquid_assets_kopecks,
        top_n=inputs.top_n,
        issues=top_issues,
        account_names=account_names,
        instrument_names=instrument_names,
    )
    return asset, account, top
