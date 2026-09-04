"""Small, deterministic, read-only financial insight rules (R07-11A / issue #178).

This module only interprets already accepted backend read models.  It does not
recalculate financial metrics, call providers, persist a result, or make a
recommendation.  A rule is allowed to emit an insight only when the source
service returned the values needed to explain that rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.orm import Session

from hermes_finance.domain.risk_allocation import RiskSupportStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.close_readiness import (
    CloseReadinessCode,
    CloseReadinessSeverity,
    build_close_readiness,
)
from hermes_finance.services.freshness_provenance import (
    FreshnessSeverity,
    build_freshness_provenance_summary,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.reporting_months import (
    close_hard_guards,
    get_reporting_month,
)
from hermes_finance.services.risk_allocation import risk_allocation_for_month
from hermes_finance.services.tax_iis_planner import (
    SALARY_TAX_HISTORY_INCOMPLETE,
    build_tax_iis_planner,
)

DETERMINISTIC_INSIGHTS_CONTRACT_VERSION = "deterministic_insights_v1"
DETERMINISTIC_INSIGHTS_RULESET_VERSION = "v1"
CONCENTRATION_THRESHOLD_PCT = Decimal("50.00")


class InsightSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class InsightPeriod:
    year: int
    month: int


@dataclass(frozen=True, slots=True)
class InsightProvenance:
    source: str
    provider: str | None = None
    observed_at: date | None = None


@dataclass(frozen=True, slots=True)
class DeterministicInsight:
    code: str
    type: str
    severity: InsightSeverity
    message: str
    evidence: dict[str, object]
    comparison_period: InsightPeriod | None
    source: str
    as_of: date | None
    provenance: tuple[InsightProvenance, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class DeterministicInsightsResult:
    contract_version: str
    ruleset_version: str
    forecast_version: str
    reporting_month_id: int
    year: int
    month: int
    status: str
    snapshot_date: date | None
    evaluated_on: date
    insights: tuple[DeterministicInsight, ...]


_SEVERITY_ORDER = {
    InsightSeverity.ERROR: 0,
    InsightSeverity.WARNING: 1,
    InsightSeverity.INFO: 2,
}


def _money(amount: RubleAmount) -> dict[str, str]:
    return {"amount": amount.to_api(), "currency": "RUB"}


def _percentage(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _coverage_evidence(coverage) -> dict[str, int]:
    return {
        "row_count": coverage.row_count,
        "current_count": coverage.current_count,
        "stale_count": coverage.stale_count,
        "unavailable_count": coverage.unavailable_count,
        "unknown_count": coverage.unknown_count,
        "missing_count": coverage.missing_count,
        "manual_count": coverage.manual_count,
        "provider_count": coverage.provider_count,
    }


def _insight(
    *,
    code: str,
    type: str,
    severity: InsightSeverity,
    message: str,
    evidence: dict[str, object],
    source: str,
    as_of: date | None,
    reason: str,
    provenance: tuple[InsightProvenance, ...] = (),
) -> DeterministicInsight:
    return DeterministicInsight(
        code=code,
        type=type,
        severity=severity,
        message=message,
        evidence=dict(evidence),
        comparison_period=None,
        source=source,
        as_of=as_of,
        provenance=provenance,
        reason=reason,
    )


def _close_guard_insights(
    *,
    month,
    blockers: tuple[tuple[str, str], ...],
) -> list[DeterministicInsight]:
    return [
        _insight(
            code=code,
            type="close_readiness",
            severity=InsightSeverity.ERROR,
            message=message,
            evidence={
                "close_readiness_code": code,
                "close_readiness_severity": CloseReadinessSeverity.HARD_BLOCKER.value,
                "can_close": False,
                "status": month.status,
                "snapshot_date": _date(month.snapshot_date),
            },
            source="close_readiness",
            as_of=month.snapshot_date,
            reason="close_readiness_returned_a_hard_blocker",
            provenance=(InsightProvenance(source="reporting_month"),),
        )
        for code, message in blockers
    ]


def _close_insights(*, month, readiness) -> list[DeterministicInsight]:
    return [
        _insight(
            code=item.code,
            type="close_readiness",
            severity=InsightSeverity.ERROR,
            message=item.message,
            evidence={
                "close_readiness_code": item.code,
                "close_readiness_severity": item.severity.value,
                "can_close": readiness.can_close,
                "status": readiness.status,
                "snapshot_date": _date(readiness.snapshot_date),
                "context": item.context,
            },
            source="close_readiness",
            as_of=month.snapshot_date,
            reason="close_readiness_returned_a_hard_blocker",
            provenance=(InsightProvenance(source="reporting_month"),),
        )
        for item in readiness.items
        if item.severity is CloseReadinessSeverity.HARD_BLOCKER
    ]


def _important_coverage_insights(*, month, readiness) -> list[DeterministicInsight]:
    """Promote the accepted actionable snapshot-coverage warning.

    Close readiness owns the account-coverage predicate and its owner-facing
    context.  Insights only transport that result; they do not recalculate
    completeness or turn an absent snapshot into zero.
    """
    return [
        _insight(
            code=item.code,
            type="data_quality",
            severity=InsightSeverity.WARNING,
            message=item.message,
            evidence={
                "close_readiness_code": item.code,
                "close_readiness_severity": item.severity.value,
                "can_close": readiness.can_close,
                "status": readiness.status,
                "snapshot_date": _date(readiness.snapshot_date),
                "context": item.context,
            },
            source="close_readiness.active_account_snapshot_missing",
            as_of=month.snapshot_date,
            reason="close_readiness_reported_missing_active_account_snapshot",
            provenance=(InsightProvenance(source="reporting_month"),),
        )
        for item in readiness.items
        if item.code == CloseReadinessCode.ACTIVE_ACCOUNT_SNAPSHOT_MISSING.value
        and item.severity is CloseReadinessSeverity.WARNING
    ]


def _payout_reconciliation_insights(
    *,
    month,
    readiness,
) -> list[DeterministicInsight]:
    return [
        _insight(
            code=CloseReadinessCode.UNRESOLVED_PAYOUT_RECONCILIATION.value,
            type="payout_reconciliation",
            severity=InsightSeverity.WARNING,
            message=item.message,
            evidence={
                "count": item.context.get("count"),
                "close_readiness_code": item.code,
                "status": readiness.status,
                "can_close": readiness.can_close,
                "snapshot_date": _date(month.snapshot_date),
            },
            source="close_readiness.unresolved_payout_reconciliation",
            as_of=month.snapshot_date,
            reason="unresolved_payout_reconciliation_count_is_positive",
            provenance=(InsightProvenance(source="merged_payout_calendar"),),
        )
        for item in readiness.items
        if item.code == CloseReadinessCode.UNRESOLVED_PAYOUT_RECONCILIATION.value
    ]


def _freshness_insights(summary) -> list[DeterministicInsight]:
    insights: list[DeterministicInsight] = []
    for family in summary.families:
        for reason in family.reasons:
            if reason.severity is not FreshnessSeverity.WARNING:
                continue
            insights.append(
                _insight(
                    code=reason.code.value,
                    type="freshness_warning",
                    severity=InsightSeverity.WARNING,
                    message=reason.message,
                    evidence={
                        "family_id": family.family_id.value,
                        "family_title": family.title,
                        "family_status": family.status.value,
                        "reason_code": reason.code.value,
                        "coverage": _coverage_evidence(family.coverage),
                        "evaluated_on": summary.evaluated_on.isoformat(),
                        "quote_valuation_target_date": summary.quote_valuation_target_date.isoformat(),
                    },
                    source="freshness_provenance",
                    as_of=summary.quote_valuation_target_date,
                    reason="freshness_reason_has_warning_severity",
                    provenance=tuple(
                        InsightProvenance(source=family.family_id.value, provider=provider)
                        for provider in family.providers
                    ),
                )
            )
    return insights


def _concentration_evidence(metric, *, scope: str) -> dict[str, object]:
    item = metric.items[0]
    return {
        "scope": scope,
        "top_item": {
            "label": item.label,
            "amount": _money(item.amount),
            "share_pct": _percentage(item.share_pct),
            "event_count": item.event_count,
            "instrument_type": item.instrument_type,
            "is_approximate": item.is_approximate,
        },
        "denominator": _money(metric.denominator),
        "top_amount": _money(metric.top_amount),
        "top_share_pct": _percentage(metric.top_share_pct),
        "top_n": metric.top_n,
        "threshold_pct": _percentage(CONCENTRATION_THRESHOLD_PCT),
        "support_status": metric.support.status.value,
        "support_reason_codes": list(metric.support.reason_codes),
        "excluded_count": len(metric.excluded),
        "is_approximate": metric.is_approximate,
    }


def _concentration_insight(
    metric,
    *,
    code: str,
    scope: str,
    message_template: str,
    as_of: date,
) -> DeterministicInsight | None:
    if not metric.items or metric.top_share_pct is None:
        return None
    if metric.top_share_pct < CONCENTRATION_THRESHOLD_PCT:
        return None

    degraded = metric.support.status is not RiskSupportStatus.SUPPORTED or metric.is_approximate
    item = metric.items[0]
    qualifier = " по доступным данным" if degraded else ""
    message = message_template.format(
        label=item.label,
        share=_percentage(item.share_pct),
        qualifier=qualifier,
    )
    return _insight(
        code=code,
        type="concentration",
        severity=InsightSeverity.INFO if degraded else InsightSeverity.WARNING,
        message=message,
        evidence=_concentration_evidence(metric, scope=scope),
        source=f"risk_allocation.{scope}",
        as_of=as_of,
        reason="top_share_pct_meets_or_exceeds_threshold",
        provenance=(InsightProvenance(source=f"risk_allocation.{scope}"),),
    )


def _risk_insights(risk_result) -> list[DeterministicInsight]:
    as_of = risk_result.as_of_date
    insights: list[DeterministicInsight] = []
    for metric, code, scope, message_template in (
        (
            risk_result.payout_concentration,
            "upcoming_payout_concentration",
            "payout_concentration",
            "Более половины ожидаемых выплат приходится на {label} ({share}%). Это описательный сигнал концентрации{qualifier}, не рекомендация.",
        ),
        (
            risk_result.redemption_concentration,
            "redemption_concentration",
            "redemption_concentration",
            "Более половины ожидаемого погашения приходится на {label} ({share}%). Это описательный сигнал концентрации{qualifier}, не рекомендация.",
        ),
        (
            risk_result.top_positions,
            "portfolio_concentration",
            "top_positions",
            "Одна позиция составляет {share}% сохранённой ликвидной стоимости портфеля: {label}. Это описательный сигнал концентрации{qualifier}, не рекомендация.",
        ),
    ):
        insight = _concentration_insight(
            metric,
            code=code,
            scope=scope,
            message_template=message_template,
            as_of=as_of,
        )
        if insight is not None:
            insights.append(insight)

    allocation = risk_result.allocation_by_asset_class
    if allocation.denominator.kopecks > 0 and allocation.unallocated_amount.kopecks > 0:
        degraded = allocation.support.status is not RiskSupportStatus.SUPPORTED
        qualifier = " по доступным данным" if degraded else ""
        insights.append(
            _insight(
                code="partial_asset_class_coverage",
                type="asset_class_coverage",
                severity=InsightSeverity.INFO if degraded else InsightSeverity.WARNING,
                message=(
                    "Не весь ликвидный портфель распределён по явным классам активов"
                    f"{qualifier}: покрыто {_percentage(allocation.coverage_pct)}%, без класса "
                    f"{allocation.unallocated_amount.to_api()} RUB."
                ),
                evidence={
                    "denominator": _money(allocation.denominator),
                    "covered_amount": _money(allocation.covered_amount),
                    "unallocated_amount": _money(allocation.unallocated_amount),
                    "coverage_pct": _percentage(allocation.coverage_pct),
                    "support_status": allocation.support.status.value,
                    "support_reason_codes": list(allocation.support.reason_codes),
                    "unknown_class_present": True,
                },
                source="risk_allocation.allocation_by_asset_class",
                as_of=as_of,
                reason="asset_class_coverage_is_below_100_percent",
                provenance=(InsightProvenance(source="risk_allocation.allocation_by_asset_class"),),
            )
        )
    return insights


def _tax_insights(session: Session, *, month) -> list[DeterministicInsight]:
    planner = build_tax_iis_planner(session, reporting_month_id=month.id)
    salary_tax = planner.salary_tax
    if SALARY_TAX_HISTORY_INCOMPLETE not in salary_tax.warning_codes:
        return []
    return [
        _insight(
            code=SALARY_TAX_HISTORY_INCOMPLETE,
            type="salary_tax",
            severity=InsightSeverity.WARNING,
            message=(
                "История зарплатного НДФЛ за текущий налоговый год неполна; "
                "текущие налоговые пороги не оцениваются."
            ),
            evidence={
                "tax_year": salary_tax.tax_year,
                "history_complete": salary_tax.history_complete,
                "available": salary_tax.available,
                "opening_context_available": salary_tax.opening_context_available,
                "warning_codes": list(salary_tax.warning_codes),
                "taxable_gross_ytd": None,
                "selection_reason": planner.selection_reason,
            },
            source="tax_iis_planner.salary_tax",
            as_of=month.snapshot_date,
            reason="tax_planner_reports_salary_tax_history_incomplete",
            provenance=(InsightProvenance(source="salary_tax_context"),),
        )
    ]


def _sort_insights(insights: list[DeterministicInsight]) -> tuple[DeterministicInsight, ...]:
    return tuple(
        sorted(
            insights,
            key=lambda item: (
                _SEVERITY_ORDER[item.severity],
                item.code,
                item.source,
                item.reason,
            ),
        )
    )


def build_deterministic_insights(
    session: Session,
    reporting_month_id: int,
    *,
    evaluated_on: date,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> DeterministicInsightsResult:
    """Build the v1 insight list for one reporting month without writing state."""
    version = forecast_version.strip()
    if not version:
        raise ValueError("forecast_version must not be empty")

    month = get_reporting_month(session, reporting_month_id)
    blockers = close_hard_guards(month)
    if month.snapshot_date is None:
        return DeterministicInsightsResult(
            contract_version=DETERMINISTIC_INSIGHTS_CONTRACT_VERSION,
            ruleset_version=DETERMINISTIC_INSIGHTS_RULESET_VERSION,
            forecast_version=version,
            reporting_month_id=month.id,
            year=month.year,
            month=month.month,
            status=month.status,
            snapshot_date=None,
            evaluated_on=evaluated_on,
            insights=_sort_insights(_close_guard_insights(month=month, blockers=blockers)),
        )

    readiness = build_close_readiness(
        session,
        month.id,
        today=evaluated_on,
        latest_backup=None,
    )
    freshness = build_freshness_provenance_summary(
        session,
        month.id,
        today=evaluated_on,
    )
    risk = risk_allocation_for_month(
        session,
        month.id,
        top_n=1,
        forecast_version=version,
    )

    insights: list[DeterministicInsight] = []
    insights.extend(_close_insights(month=month, readiness=readiness))
    insights.extend(_important_coverage_insights(month=month, readiness=readiness))
    insights.extend(_freshness_insights(freshness))
    insights.extend(_payout_reconciliation_insights(month=month, readiness=readiness))
    insights.extend(_risk_insights(risk))
    insights.extend(_tax_insights(session, month=month))
    return DeterministicInsightsResult(
        contract_version=DETERMINISTIC_INSIGHTS_CONTRACT_VERSION,
        ruleset_version=DETERMINISTIC_INSIGHTS_RULESET_VERSION,
        forecast_version=version,
        reporting_month_id=month.id,
        year=month.year,
        month=month.month,
        status=month.status,
        snapshot_date=month.snapshot_date,
        evaluated_on=evaluated_on,
        insights=_sort_insights(insights),
    )


deterministic_insights_for_month = build_deterministic_insights
