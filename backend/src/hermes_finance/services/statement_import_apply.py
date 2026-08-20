"""Transactional owner-selected statement apply orchestration for R06-08.

Re-parses the provided document through the accepted R06-07 path, rebuilds
a fresh preview against current Hermes state, and applies the selected set
in one transaction. Caller-supplied amounts are never trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import ReportingMonthStatus, RubleAmount
from hermes_finance.persistence import Account, Instrument, InvestmentCashFlow, ReportingMonth
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.applied_statement_events import (
    StatementLinkMode,
    StatementRevisionKind,
    append_applied_statement_revision,
    create_applied_statement_event,
    get_applied_statement_event_by_identity,
    list_applied_statement_event_revisions,
    list_linked_investment_cash_flow_ids,
    load_prior_event_views,
)
from hermes_finance.services.investment_cash_flows import (
    stage_create_investment_cash_flow,
    stage_update_investment_cash_flow,
)
from hermes_finance.services.reporting_months import get_reporting_month_by_period
from hermes_finance.statement_import.dto import (
    ALFA_DEPOSITORY_INCOME_PROVIDER,
    AccountMappingInput,
    HermesAccountView,
    HermesInstrumentView,
    InstrumentMappingInput,
    PreviewRow,
    ReportStatus,
    RowStatus,
)
from hermes_finance.statement_import.money import kopecks
from hermes_finance.statement_import.preview import preview_income_report


class StatementApplyFailureCode(StrEnum):
    PREVIEW_CHANGED = "preview_changed"
    CLOSED_MONTH = "closed_month"
    MISSING_REPORTING_MONTH = "missing_reporting_month"
    DUPLICATE_RESOLUTION_REQUIRED = "duplicate_resolution_required"
    MANUAL_LINK_CONFLICT = "manual_link_conflict"
    VALIDATION_ERROR = "validation_error"
    PERSISTENCE_ERROR = "persistence_error"
    MALFORMED_OR_UNSUPPORTED_REPORT = "malformed_or_unsupported_report"


class StatementApplyAction(StrEnum):
    REVISE = "revise"
    CREATE_SEPARATE = "create_separate"
    LINK_EXISTING = "link_existing"


class StatementApplyItemAction(StrEnum):
    CREATED = "created"
    LINKED_EXISTING = "linked_existing"
    REVISED = "revised"
    UNCHANGED = "unchanged"


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class StatementApplySelection:
    natural_identity: str
    material_fingerprint: str
    action: StatementApplyAction | None = None
    existing_cash_flow_id: int | None = None
    expected_candidate_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        identity = self.natural_identity
        fingerprint = self.material_fingerprint
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("natural_identity must not be empty")
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            raise ValueError("material_fingerprint must not be empty")
        object.__setattr__(self, "natural_identity", identity.strip())
        object.__setattr__(self, "material_fingerprint", fingerprint.strip())
        if self.action is not None:
            try:
                object.__setattr__(self, "action", StatementApplyAction(self.action))
            except (TypeError, ValueError) as error:
                raise ValueError("unsupported statement apply action") from error
        if self.action is StatementApplyAction.LINK_EXISTING:
            object.__setattr__(
                self,
                "existing_cash_flow_id",
                _positive_int(self.existing_cash_flow_id, name="existing_cash_flow_id"),
            )
        elif self.existing_cash_flow_id is not None:
            raise ValueError("existing_cash_flow_id is only valid with link_existing")
        ids: list[int] = []
        seen: set[int] = set()
        for candidate_id in self.expected_candidate_ids:
            normalized = _positive_int(candidate_id, name="expected_candidate_ids")
            if normalized in seen:
                raise ValueError("expected_candidate_ids must be unique")
            seen.add(normalized)
            ids.append(normalized)
        object.__setattr__(self, "expected_candidate_ids", tuple(ids))


@dataclass(frozen=True, slots=True)
class StatementApplyItemResult:
    action: StatementApplyItemAction
    applied_statement_event_id: int
    investment_cash_flow_id: int
    natural_identity: str
    material_fingerprint: str
    revision_id: int | None = None


@dataclass(frozen=True, slots=True)
class StatementApplyResult:
    success: bool
    selected_count: int
    items: tuple[StatementApplyItemResult, ...] = ()
    error_code: StatementApplyFailureCode | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class _ApplyPlan:
    selection: StatementApplySelection
    row: PreviewRow
    existing_event_id: int | None
    existing_link_mode: StatementLinkMode | None
    existing_cash_flow_id: int | None
    candidate_ids: tuple[int, ...]
    reporting_month_id: int | None
    writes: bool
    item_action: StatementApplyItemAction


def apply_income_report_preview(
    session: Session,
    *,
    document: bytes,
    account_mappings: tuple[AccountMappingInput, ...],
    selections: tuple[StatementApplySelection, ...],
    instrument_mappings: tuple[InstrumentMappingInput, ...] = (),
    applied_at: datetime | None = None,
) -> StatementApplyResult:
    """Re-parse, rebuild R06-07 preview, and atomically apply the selected set."""

    selected_count = len(selections)
    if not isinstance(document, (bytes, bytearray)):
        return _failure(
            selected_count,
            StatementApplyFailureCode.VALIDATION_ERROR,
            "statement document bytes are required",
        )
    if not selections:
        return _failure(
            selected_count,
            StatementApplyFailureCode.VALIDATION_ERROR,
            "at least one statement row must be selected",
        )
    if session.new or session.dirty or session.deleted:
        return _failure(
            selected_count,
            StatementApplyFailureCode.VALIDATION_ERROR,
            "statement apply requires a clean database session",
        )
    if _has_duplicate_selections(selections):
        return _failure(
            selected_count,
            StatementApplyFailureCode.VALIDATION_ERROR,
            "selected statement identities must be unique",
        )
    try:
        accepted_at = _timestamp(applied_at)
    except TypeError:
        return _failure(
            selected_count,
            StatementApplyFailureCode.VALIDATION_ERROR,
            "statement apply timestamp must be a datetime value",
        )

    session.rollback()

    try:
        fresh_preview = preview_income_report(
            bytes(document),
            hermes_accounts=_account_views(session),
            hermes_instruments=_instrument_views(session),
            account_mappings=account_mappings,
            instrument_mappings=instrument_mappings,
            prior_events=load_prior_event_views(session),
        )
    except Exception:
        return _failure(
            selected_count,
            StatementApplyFailureCode.MALFORMED_OR_UNSUPPORTED_REPORT,
            "statement report is malformed or unsupported",
        )
    if fresh_preview.status is not ReportStatus.APPLICABLE:
        return _failure(
            selected_count,
            StatementApplyFailureCode.MALFORMED_OR_UNSUPPORTED_REPORT,
            "statement report is malformed or unsupported",
        )

    plan_result = _build_apply_plan(session, fresh_preview.rows, selections)
    if isinstance(plan_result, StatementApplyResult):
        return plan_result
    plans = plan_result

    item_results: list[StatementApplyItemResult] = []
    try:
        wrote = False
        for plan in plans:
            item = _stage_plan(
                session,
                plan=plan,
                document_sha256=fresh_preview.document_sha256,
                applied_at=accepted_at,
            )
            item_results.append(item)
            if plan.writes:
                wrote = True
        if wrote:
            session.commit()
    except Exception:
        session.rollback()
        return _failure(
            selected_count,
            StatementApplyFailureCode.PERSISTENCE_ERROR,
            "statement apply persistence failed",
        )

    return StatementApplyResult(
        success=True,
        selected_count=selected_count,
        items=tuple(item_results),
    )


def _failure(
    selected_count: int,
    code: StatementApplyFailureCode,
    message: str,
) -> StatementApplyResult:
    return StatementApplyResult(
        success=False,
        selected_count=selected_count,
        error_code=code,
        message=message,
    )


def _preview_changed(selected_count: int) -> StatementApplyResult:
    return _failure(
        selected_count,
        StatementApplyFailureCode.PREVIEW_CHANGED,
        "statement preview changed; re-review before apply",
    )


def _timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if not isinstance(value, datetime):
        raise TypeError("applied_at must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _has_duplicate_selections(selections: tuple[StatementApplySelection, ...]) -> bool:
    seen: set[str] = set()
    for selection in selections:
        if selection.natural_identity in seen:
            return True
        seen.add(selection.natural_identity)
    return False


def _account_views(session: Session) -> tuple[HermesAccountView, ...]:
    accounts = session.scalars(select(Account).order_by(Account.id))
    return tuple(
        HermesAccountView(
            account_id=account.id,
            account_type=account.account_type,
            name=account.name,
        )
        for account in accounts
    )


def _instrument_views(session: Session) -> tuple[HermesInstrumentView, ...]:
    instruments = session.scalars(select(Instrument).order_by(Instrument.id))
    return tuple(
        HermesInstrumentView(
            instrument_id=instrument.id,
            isin=instrument.isin,
            name=instrument.name,
            ticker=instrument.ticker,
        )
        for instrument in instruments
    )


def _candidate_flows(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: str,
    event_date: date,
) -> tuple[InvestmentCashFlow, ...]:
    linked = list_linked_investment_cash_flow_ids(session)
    rows = session.scalars(
        select(InvestmentCashFlow)
        .where(
            InvestmentCashFlow.reporting_month_id == reporting_month_id,
            InvestmentCashFlow.account_id == account_id,
            InvestmentCashFlow.instrument_id == instrument_id,
            InvestmentCashFlow.flow_type == flow_type,
            InvestmentCashFlow.event_date == event_date,
        )
        .order_by(InvestmentCashFlow.id)
    )
    return tuple(flow for flow in rows if flow.id not in linked)


def _cash_flow_tax_kopecks(row: PreviewRow) -> int | StatementApplyFailureCode:
    if row.tax_available:
        if row.tax_amount is None:
            return StatementApplyFailureCode.VALIDATION_ERROR
        return kopecks(row.tax_amount)
    if row.gross_amount is None or row.net_amount is None:
        return StatementApplyFailureCode.VALIDATION_ERROR
    if kopecks(row.gross_amount) != kopecks(row.net_amount):
        return StatementApplyFailureCode.VALIDATION_ERROR
    return 0


def _provenance_tax_kopecks(row: PreviewRow) -> int | None:
    if not row.tax_available or row.tax_amount is None:
        return None
    return kopecks(row.tax_amount)


def _financially_compatible(flow: InvestmentCashFlow, row: PreviewRow) -> bool:
    tax = _cash_flow_tax_kopecks(row)
    if isinstance(tax, StatementApplyFailureCode):
        return False
    assert row.gross_amount is not None
    assert row.net_amount is not None
    assert row.event_date is not None
    assert row.event_kind is not None
    return (
        flow.account_id == row.hermes_account_id
        and flow.instrument_id == row.hermes_instrument_id
        and flow.flow_type == row.event_kind
        and flow.event_date == row.event_date
        and flow.gross_amount_kopecks == kopecks(row.gross_amount)
        and flow.tax_amount_kopecks == tax
        and flow.commission_amount_kopecks == 0
        and flow.net_amount_kopecks == kopecks(row.net_amount)
        and flow.currency == "RUB"
    )


def _resolve_month(session: Session, row: PreviewRow) -> ReportingMonth | None:
    if row.event_date is None:
        return None
    return get_reporting_month_by_period(
        session, year=row.event_date.year, month=row.event_date.month
    )


def _build_apply_plan(
    session: Session,
    rows: tuple[PreviewRow, ...],
    selections: tuple[StatementApplySelection, ...],
) -> tuple[_ApplyPlan, ...] | StatementApplyResult:
    selected_count = len(selections)
    by_identity: dict[str, list[PreviewRow]] = {}
    for row in rows:
        if not row.natural_identity:
            continue
        by_identity.setdefault(row.natural_identity, []).append(row)

    plans: list[_ApplyPlan] = []
    missing_month = False
    closed_month = False
    duplicate_required = False
    manual_conflict = False
    validation = False

    for selection in selections:
        matches = by_identity.get(selection.natural_identity, [])
        if len(matches) != 1:
            return _preview_changed(selected_count)
        row = matches[0]
        if (
            row.material_fingerprint is None
            or row.material_fingerprint != selection.material_fingerprint
        ):
            return _preview_changed(selected_count)
        if (
            row.status is not RowStatus.MATCHED
            or row.hermes_account_id is None
            or row.hermes_instrument_id is None
            or row.event_kind is None
            or row.isin is None
            or row.record_date is None
            or row.event_date is None
            or row.quantity is None
            or row.per_unit is None
            or row.gross_amount is None
            or row.net_amount is None
            or row.natural_identity is None
            or row.material_fingerprint is None
        ):
            validation = True
            continue

        existing = get_applied_statement_event_by_identity(
            session,
            provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
            natural_identity=row.natural_identity,
        )
        if existing is not None and (
            existing.account_id != row.hermes_account_id
            or existing.instrument_id != row.hermes_instrument_id
            or existing.event_kind != row.event_kind
            or existing.isin != row.isin
            or existing.record_date != row.record_date
        ):
            return _preview_changed(selected_count)

        month = _resolve_month(session, row)
        month_id = month.id if month is not None else None
        candidates: tuple[InvestmentCashFlow, ...] = ()
        if existing is None and month is not None:
            candidates = _candidate_flows(
                session,
                reporting_month_id=month.id,
                account_id=row.hermes_account_id,
                instrument_id=row.hermes_instrument_id,
                flow_type=row.event_kind,
                event_date=row.event_date,
            )
        candidate_ids = tuple(flow.id for flow in candidates)
        expected_ids = frozenset(selection.expected_candidate_ids)
        current_ids = frozenset(candidate_ids)

        if existing is not None and existing.material_fingerprint == row.material_fingerprint:
            item_action = StatementApplyItemAction.UNCHANGED
            writes = False
            if month is None:
                missing_month = True
            plans.append(
                _ApplyPlan(
                    selection=selection,
                    row=row,
                    existing_event_id=existing.id,
                    existing_link_mode=StatementLinkMode(existing.link_mode),
                    existing_cash_flow_id=existing.investment_cash_flow_id,
                    candidate_ids=candidate_ids,
                    reporting_month_id=month_id,
                    writes=writes,
                    item_action=item_action,
                )
            )
            continue

        if month is None:
            missing_month = True
            continue
        if month.status == ReportingMonthStatus.CLOSED.value:
            closed_month = True
            continue

        if existing is not None:
            if StatementLinkMode(existing.link_mode) is StatementLinkMode.LINKED_EXISTING:
                manual_conflict = True
                continue
            if selection.action is not StatementApplyAction.REVISE:
                validation = True
                continue
            tax = _cash_flow_tax_kopecks(row)
            if isinstance(tax, StatementApplyFailureCode):
                validation = True
                continue
            plans.append(
                _ApplyPlan(
                    selection=selection,
                    row=row,
                    existing_event_id=existing.id,
                    existing_link_mode=StatementLinkMode(existing.link_mode),
                    existing_cash_flow_id=existing.investment_cash_flow_id,
                    candidate_ids=candidate_ids,
                    reporting_month_id=month.id,
                    writes=True,
                    item_action=StatementApplyItemAction.REVISED,
                )
            )
            continue

        if current_ids != expected_ids:
            if selection.action is None and not expected_ids and current_ids:
                duplicate_required = True
                continue
            return _preview_changed(selected_count)

        if candidates:
            if selection.action is None:
                duplicate_required = True
                continue
            if selection.action is StatementApplyAction.CREATE_SEPARATE:
                tax = _cash_flow_tax_kopecks(row)
                if isinstance(tax, StatementApplyFailureCode):
                    validation = True
                    continue
                plans.append(
                    _ApplyPlan(
                        selection=selection,
                        row=row,
                        existing_event_id=None,
                        existing_link_mode=None,
                        existing_cash_flow_id=None,
                        candidate_ids=candidate_ids,
                        reporting_month_id=month.id,
                        writes=True,
                        item_action=StatementApplyItemAction.CREATED,
                    )
                )
                continue
            if selection.action is StatementApplyAction.LINK_EXISTING:
                assert selection.existing_cash_flow_id is not None
                if selection.existing_cash_flow_id not in candidate_ids:
                    return _preview_changed(selected_count)
                target = next(
                    flow for flow in candidates if flow.id == selection.existing_cash_flow_id
                )
                if not _financially_compatible(target, row):
                    validation = True
                    continue
                plans.append(
                    _ApplyPlan(
                        selection=selection,
                        row=row,
                        existing_event_id=None,
                        existing_link_mode=None,
                        existing_cash_flow_id=target.id,
                        candidate_ids=candidate_ids,
                        reporting_month_id=month.id,
                        writes=True,
                        item_action=StatementApplyItemAction.LINKED_EXISTING,
                    )
                )
                continue
            validation = True
            continue

        if selection.action is StatementApplyAction.LINK_EXISTING:
            return _preview_changed(selected_count)
        if selection.action is StatementApplyAction.REVISE:
            validation = True
            continue
        tax = _cash_flow_tax_kopecks(row)
        if isinstance(tax, StatementApplyFailureCode):
            validation = True
            continue
        plans.append(
            _ApplyPlan(
                selection=selection,
                row=row,
                existing_event_id=None,
                existing_link_mode=None,
                existing_cash_flow_id=None,
                candidate_ids=candidate_ids,
                reporting_month_id=month.id,
                writes=True,
                item_action=StatementApplyItemAction.CREATED,
            )
        )

    if missing_month:
        return _failure(
            selected_count,
            StatementApplyFailureCode.MISSING_REPORTING_MONTH,
            "reporting month for the payment date does not exist",
        )
    if closed_month:
        return _failure(
            selected_count,
            StatementApplyFailureCode.CLOSED_MONTH,
            "closed reporting month must be reopened before statement apply",
        )
    if duplicate_required:
        return _failure(
            selected_count,
            StatementApplyFailureCode.DUPLICATE_RESOLUTION_REQUIRED,
            "explicit create_separate or link_existing is required",
        )
    if manual_conflict:
        return _failure(
            selected_count,
            StatementApplyFailureCode.MANUAL_LINK_CONFLICT,
            "correction of a linked owner cash flow requires manual resolution",
        )
    if validation or len(plans) != selected_count:
        return _failure(
            selected_count,
            StatementApplyFailureCode.VALIDATION_ERROR,
            "selected statement row cannot be applied",
        )
    return tuple(plans)


def _ruble_api(kopeck_value: int) -> str:
    return RubleAmount(kopeck_value).to_api()


def _stage_plan(
    session: Session,
    *,
    plan: _ApplyPlan,
    document_sha256: str,
    applied_at: datetime,
) -> StatementApplyItemResult:
    row = plan.row
    assert row.hermes_account_id is not None
    assert row.hermes_instrument_id is not None
    assert row.event_kind is not None
    assert row.isin is not None
    assert row.record_date is not None
    assert row.event_date is not None
    assert row.quantity is not None
    assert row.per_unit is not None
    assert row.gross_amount is not None
    assert row.net_amount is not None
    assert row.natural_identity is not None
    assert row.material_fingerprint is not None
    cash_flow_tax = _cash_flow_tax_kopecks(row)
    if isinstance(cash_flow_tax, StatementApplyFailureCode):
        raise ValueError("statement row tax cannot be mapped")
    provenance_tax = _provenance_tax_kopecks(row)

    if plan.item_action is StatementApplyItemAction.UNCHANGED:
        assert plan.existing_event_id is not None
        assert plan.existing_cash_flow_id is not None
        return StatementApplyItemResult(
            action=StatementApplyItemAction.UNCHANGED,
            applied_statement_event_id=plan.existing_event_id,
            investment_cash_flow_id=plan.existing_cash_flow_id,
            natural_identity=row.natural_identity,
            material_fingerprint=row.material_fingerprint,
        )

    if plan.item_action is StatementApplyItemAction.CREATED:
        assert plan.reporting_month_id is not None
        require_editable_reporting_month(session, plan.reporting_month_id)
        flow = stage_create_investment_cash_flow(
            session,
            reporting_month_id=plan.reporting_month_id,
            account_id=row.hermes_account_id,
            instrument_id=row.hermes_instrument_id,
            flow_type=row.event_kind,
            event_date=row.event_date,
            gross_amount=_ruble_api(kopecks(row.gross_amount)),
            tax_amount=_ruble_api(cash_flow_tax),
            commission_amount="0.00",
            net_amount=_ruble_api(kopecks(row.net_amount)),
            currency="RUB",
            source=ALFA_DEPOSITORY_INCOME_PROVIDER,
        )
        event = create_applied_statement_event(
            session,
            provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
            account_id=row.hermes_account_id,
            instrument_id=row.hermes_instrument_id,
            event_kind=row.event_kind,
            isin=row.isin,
            record_date=row.record_date,
            natural_identity=row.natural_identity,
            material_fingerprint=row.material_fingerprint,
            investment_cash_flow_id=flow.id,
            document_sha256=document_sha256,
            link_mode=StatementLinkMode.STATEMENT_CREATED,
            event_date=row.event_date,
            quantity=row.quantity,
            per_unit=row.per_unit,
            gross_amount_kopecks=kopecks(row.gross_amount),
            gross_currency="RUB",
            tax_available=row.tax_available,
            tax_amount_kopecks=provenance_tax,
            tax_rate=row.tax_rate,
            net_amount_kopecks=kopecks(row.net_amount),
            net_currency="RUB",
            applied_at=applied_at,
        )
        revision = list_applied_statement_event_revisions(session, event.id)[-1]
        return StatementApplyItemResult(
            action=StatementApplyItemAction.CREATED,
            applied_statement_event_id=event.id,
            investment_cash_flow_id=flow.id,
            natural_identity=row.natural_identity,
            material_fingerprint=row.material_fingerprint,
            revision_id=revision.id,
        )

    if plan.item_action is StatementApplyItemAction.LINKED_EXISTING:
        assert plan.existing_cash_flow_id is not None
        event = create_applied_statement_event(
            session,
            provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
            account_id=row.hermes_account_id,
            instrument_id=row.hermes_instrument_id,
            event_kind=row.event_kind,
            isin=row.isin,
            record_date=row.record_date,
            natural_identity=row.natural_identity,
            material_fingerprint=row.material_fingerprint,
            investment_cash_flow_id=plan.existing_cash_flow_id,
            document_sha256=document_sha256,
            link_mode=StatementLinkMode.LINKED_EXISTING,
            event_date=row.event_date,
            quantity=row.quantity,
            per_unit=row.per_unit,
            gross_amount_kopecks=kopecks(row.gross_amount),
            gross_currency="RUB",
            tax_available=row.tax_available,
            tax_amount_kopecks=provenance_tax,
            tax_rate=row.tax_rate,
            net_amount_kopecks=kopecks(row.net_amount),
            net_currency="RUB",
            applied_at=applied_at,
        )
        revision = list_applied_statement_event_revisions(session, event.id)[-1]
        return StatementApplyItemResult(
            action=StatementApplyItemAction.LINKED_EXISTING,
            applied_statement_event_id=event.id,
            investment_cash_flow_id=plan.existing_cash_flow_id,
            natural_identity=row.natural_identity,
            material_fingerprint=row.material_fingerprint,
            revision_id=revision.id,
        )

    assert plan.item_action is StatementApplyItemAction.REVISED
    assert plan.existing_event_id is not None
    assert plan.existing_cash_flow_id is not None
    assert plan.reporting_month_id is not None
    stage_update_investment_cash_flow(
        session,
        plan.existing_cash_flow_id,
        event_date=row.event_date,
        gross_amount=_ruble_api(kopecks(row.gross_amount)),
        tax_amount=_ruble_api(cash_flow_tax),
        commission_amount="0.00",
        net_amount=_ruble_api(kopecks(row.net_amount)),
        currency="RUB",
        reporting_month_id=plan.reporting_month_id,
    )
    revision = append_applied_statement_revision(
        session,
        plan.existing_event_id,
        revision_kind=StatementRevisionKind.REVISE,
        document_sha256=document_sha256,
        natural_identity=row.natural_identity,
        material_fingerprint=row.material_fingerprint,
        account_id=row.hermes_account_id,
        instrument_id=row.hermes_instrument_id,
        event_kind=row.event_kind,
        isin=row.isin,
        record_date=row.record_date,
        event_date=row.event_date,
        quantity=row.quantity,
        per_unit=row.per_unit,
        gross_amount_kopecks=kopecks(row.gross_amount),
        gross_currency="RUB",
        tax_available=row.tax_available,
        tax_amount_kopecks=provenance_tax,
        tax_rate=row.tax_rate,
        net_amount_kopecks=kopecks(row.net_amount),
        net_currency="RUB",
        applied_at=applied_at,
    )
    return StatementApplyItemResult(
        action=StatementApplyItemAction.REVISED,
        applied_statement_event_id=plan.existing_event_id,
        investment_cash_flow_id=plan.existing_cash_flow_id,
        natural_identity=row.natural_identity,
        material_fingerprint=row.material_fingerprint,
        revision_id=revision.id,
    )
