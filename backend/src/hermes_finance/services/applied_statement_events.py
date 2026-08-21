"""Applied statement-event persistence primitives (R06-08).

Schema/repository only. These helpers do not parse PDFs, preview, apply a
selected set, or mutate cash-flow rows. Callers own the transaction: writes
flush and do not commit.

Raw PDF bytes, extracted text, provider depository-account refs and
beneficiary data are never accepted or stored.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import FINANCIAL_ROUNDING, InvestmentCashFlowType
from hermes_finance.persistence import (
    Account,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    Instrument,
    InvestmentCashFlow,
)
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.instruments import InstrumentNotFoundError
from hermes_finance.services.investment_cash_flows import InvestmentCashFlowNotFoundError
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER, PriorEventView

_QUANT = Decimal("0.00000001")
_SHA256_HEX_LENGTH = 64
_ALLOWED_KINDS = {
    InvestmentCashFlowType.DIVIDEND.value,
    InvestmentCashFlowType.COUPON.value,
    InvestmentCashFlowType.REDEMPTION.value,
}


class AppliedStatementEventAlreadyExistsError(ValueError):
    pass


class AppliedStatementEventNotFoundError(LookupError):
    pass


class AppliedStatementRevisionError(ValueError):
    """Raised when a caller tries to treat historical revision evidence as mutable."""


class StatementLinkMode(StrEnum):
    STATEMENT_CREATED = "statement_created"
    LINKED_EXISTING = "linked_existing"


class StatementRevisionKind(StrEnum):
    APPLY = "apply"
    REVISE = "revise"
    LINK_EXISTING = "link_existing"


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _require_instrument(session: Session, instrument_id: int) -> None:
    if session.get(Instrument, instrument_id) is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")


def _require_cash_flow(session: Session, cash_flow_id: int) -> InvestmentCashFlow:
    flow = session.get(InvestmentCashFlow, cash_flow_id)
    if flow is None:
        raise InvestmentCashFlowNotFoundError(f"investment cash flow {cash_flow_id} was not found")
    return flow


def _require_text(value: str, *, name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _require_sha256(value: str, *, name: str) -> str:
    digest = _require_text(value, name=name).lower()
    if len(digest) != _SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return digest


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


def _require_decimal(value: Decimal, *, name: str) -> Decimal:
    if isinstance(value, float) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def canonical_decimal_text(value: Decimal) -> str:
    quantized = value.quantize(_QUANT, rounding=FINANCIAL_ROUNDING)
    return format(quantized, "f")


def _coerce_kind(value: str) -> str:
    kind = _require_text(value, name="event_kind")
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"unsupported statement event kind: {value!r}")
    return kind


def _coerce_link_mode(value: StatementLinkMode | str) -> StatementLinkMode:
    try:
        return StatementLinkMode(value)
    except ValueError as error:
        raise ValueError(f"unsupported statement link mode: {value!r}") from error


def _coerce_revision_kind(value: StatementRevisionKind | str) -> StatementRevisionKind:
    try:
        return StatementRevisionKind(value)
    except ValueError as error:
        raise ValueError(f"unsupported statement revision kind: {value!r}") from error


def _require_nonnegative_kopecks(value: int, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _tax_amount_for_provenance(
    *, tax_available: bool, tax_amount_kopecks: int | None
) -> int | None:
    if tax_available:
        if tax_amount_kopecks is None:
            raise ValueError("explicit tax evidence requires tax_amount_kopecks")
        return _require_nonnegative_kopecks(tax_amount_kopecks, name="tax_amount_kopecks")
    if tax_amount_kopecks is not None:
        raise ValueError("unavailable tax must not persist a numeric tax amount")
    return None


def get_applied_statement_event(session: Session, event_id: int) -> AppliedStatementEvent:
    event = session.get(AppliedStatementEvent, event_id)
    if event is None:
        raise AppliedStatementEventNotFoundError(
            f"applied statement event {event_id} was not found"
        )
    return event


def get_applied_statement_event_by_identity(
    session: Session,
    *,
    provider: str,
    natural_identity: str,
) -> AppliedStatementEvent | None:
    return session.scalar(
        select(AppliedStatementEvent).where(
            AppliedStatementEvent.provider == provider,
            AppliedStatementEvent.natural_identity == natural_identity,
        )
    )


def get_applied_statement_event_by_cash_flow(
    session: Session, investment_cash_flow_id: int
) -> AppliedStatementEvent | None:
    return session.scalar(
        select(AppliedStatementEvent).where(
            AppliedStatementEvent.investment_cash_flow_id == investment_cash_flow_id
        )
    )


def list_applied_statement_events(session: Session) -> list[AppliedStatementEvent]:
    return list(session.scalars(select(AppliedStatementEvent).order_by(AppliedStatementEvent.id)))


def list_applied_statement_event_revisions(
    session: Session, event_id: int
) -> list[AppliedStatementEventRevision]:
    get_applied_statement_event(session, event_id)
    return list(
        session.scalars(
            select(AppliedStatementEventRevision)
            .where(AppliedStatementEventRevision.applied_statement_event_id == event_id)
            .order_by(AppliedStatementEventRevision.id)
        )
    )


def load_prior_event_views(session: Session) -> tuple[PriorEventView, ...]:
    return tuple(
        PriorEventView(
            natural_identity=event.natural_identity,
            material_fingerprint=event.material_fingerprint,
        )
        for event in list_applied_statement_events(session)
    )


def list_linked_investment_cash_flow_ids(session: Session) -> set[int]:
    return set(session.scalars(select(AppliedStatementEvent.investment_cash_flow_id)))


def _append_revision_row(
    session: Session,
    *,
    event: AppliedStatementEvent,
    revision_kind: StatementRevisionKind,
    document_sha256: str,
    natural_identity: str,
    material_fingerprint: str,
    account_id: int,
    instrument_id: int,
    event_kind: str,
    isin: str,
    record_date: date,
    event_date: date,
    quantity: Decimal,
    per_unit: Decimal,
    gross_amount_kopecks: int,
    gross_currency: str,
    tax_available: bool,
    tax_amount_kopecks: int | None,
    tax_rate: Decimal | None,
    net_amount_kopecks: int,
    net_currency: str,
    applied_at: datetime,
) -> AppliedStatementEventRevision:
    if revision_kind is StatementRevisionKind.APPLY:
        existing = list_applied_statement_event_revisions(session, event.id)
        if existing:
            raise AppliedStatementRevisionError(
                "first apply is recorded once; later history must not reuse apply"
            )
    revision = AppliedStatementEventRevision(
        applied_statement_event_id=event.id,
        revision_kind=revision_kind.value,
        document_sha256=document_sha256,
        natural_identity=natural_identity,
        material_fingerprint=material_fingerprint,
        account_id=account_id,
        instrument_id=instrument_id,
        event_kind=event_kind,
        isin=isin,
        record_date=record_date,
        event_date=event_date,
        quantity=canonical_decimal_text(_require_decimal(quantity, name="quantity")),
        per_unit=canonical_decimal_text(_require_decimal(per_unit, name="per_unit")),
        gross_amount_kopecks=_require_nonnegative_kopecks(
            gross_amount_kopecks, name="gross_amount_kopecks"
        ),
        gross_currency=_require_text(gross_currency, name="gross_currency").upper(),
        tax_available=bool(tax_available),
        tax_amount_kopecks=_tax_amount_for_provenance(
            tax_available=bool(tax_available),
            tax_amount_kopecks=tax_amount_kopecks,
        ),
        tax_rate=(
            canonical_decimal_text(_require_decimal(tax_rate, name="tax_rate"))
            if tax_rate is not None
            else None
        ),
        net_amount_kopecks=_require_nonnegative_kopecks(
            net_amount_kopecks, name="net_amount_kopecks"
        ),
        net_currency=_require_text(net_currency, name="net_currency").upper(),
        applied_at=applied_at,
    )
    session.add(revision)
    return revision


def create_applied_statement_event(
    session: Session,
    *,
    provider: str,
    account_id: int,
    instrument_id: int,
    event_kind: str,
    isin: str,
    record_date: date,
    natural_identity: str,
    material_fingerprint: str,
    investment_cash_flow_id: int,
    document_sha256: str,
    link_mode: StatementLinkMode | str,
    event_date: date,
    quantity: Decimal,
    per_unit: Decimal,
    gross_amount_kopecks: int,
    gross_currency: str,
    tax_available: bool,
    tax_amount_kopecks: int | None,
    tax_rate: Decimal | None,
    net_amount_kopecks: int,
    net_currency: str,
    applied_at: datetime | None = None,
) -> AppliedStatementEvent:
    provider_name = _require_text(provider, name="provider")
    if provider_name != ALFA_DEPOSITORY_INCOME_PROVIDER:
        raise ValueError("unsupported statement provider")
    _require_account(session, account_id)
    _require_instrument(session, instrument_id)
    flow = _require_cash_flow(session, investment_cash_flow_id)
    if flow.account_id != account_id or flow.instrument_id != instrument_id:
        raise ValueError("linked cash flow must match statement account and instrument")
    kind = _coerce_kind(event_kind)
    identity = _require_text(natural_identity, name="natural_identity")
    fingerprint = _require_sha256(material_fingerprint, name="material_fingerprint")
    digest = _require_sha256(document_sha256, name="document_sha256")
    mode = _coerce_link_mode(link_mode)
    revision_kind = (
        StatementRevisionKind.LINK_EXISTING
        if mode is StatementLinkMode.LINKED_EXISTING
        else StatementRevisionKind.APPLY
    )
    existing = get_applied_statement_event_by_identity(
        session, provider=provider_name, natural_identity=identity
    )
    if existing is not None:
        raise AppliedStatementEventAlreadyExistsError(
            "applied statement event already exists for this natural identity"
        )
    if get_applied_statement_event_by_cash_flow(session, investment_cash_flow_id) is not None:
        raise AppliedStatementEventAlreadyExistsError(
            "investment cash flow is already linked to a statement event"
        )
    accepted_at = _require_timestamp(applied_at or datetime.now(UTC), name="applied_at")
    event = AppliedStatementEvent(
        provider=provider_name,
        account_id=account_id,
        instrument_id=instrument_id,
        event_kind=kind,
        isin=_require_text(isin, name="isin").upper(),
        record_date=_require_date(record_date, name="record_date"),
        natural_identity=identity,
        material_fingerprint=fingerprint,
        investment_cash_flow_id=flow.id,
        document_sha256=digest,
        link_mode=mode.value,
        created_at=accepted_at,
        updated_at=accepted_at,
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError as error:
        raise AppliedStatementEventAlreadyExistsError(
            "applied statement event already exists for this natural identity"
        ) from error
    _append_revision_row(
        session,
        event=event,
        revision_kind=revision_kind,
        document_sha256=digest,
        natural_identity=identity,
        material_fingerprint=fingerprint,
        account_id=account_id,
        instrument_id=instrument_id,
        event_kind=kind,
        isin=event.isin,
        record_date=event.record_date,
        event_date=_require_date(event_date, name="event_date"),
        quantity=quantity,
        per_unit=per_unit,
        gross_amount_kopecks=gross_amount_kopecks,
        gross_currency=gross_currency,
        tax_available=tax_available,
        tax_amount_kopecks=tax_amount_kopecks,
        tax_rate=tax_rate,
        net_amount_kopecks=net_amount_kopecks,
        net_currency=net_currency,
        applied_at=accepted_at,
    )
    session.flush()
    return event


def append_applied_statement_revision(
    session: Session,
    event_id: int,
    *,
    revision_kind: StatementRevisionKind | str,
    document_sha256: str,
    natural_identity: str,
    material_fingerprint: str,
    account_id: int,
    instrument_id: int,
    event_kind: str,
    isin: str,
    record_date: date,
    event_date: date,
    quantity: Decimal,
    per_unit: Decimal,
    gross_amount_kopecks: int,
    gross_currency: str,
    tax_available: bool,
    tax_amount_kopecks: int | None,
    tax_rate: Decimal | None,
    net_amount_kopecks: int,
    net_currency: str,
    applied_at: datetime | None = None,
) -> AppliedStatementEventRevision:
    event = get_applied_statement_event(session, event_id)
    kind = _coerce_revision_kind(revision_kind)
    if kind is StatementRevisionKind.APPLY:
        raise AppliedStatementRevisionError(
            "first apply is recorded by create_applied_statement_event; "
            "later history must not reuse apply"
        )
    if kind is StatementRevisionKind.LINK_EXISTING:
        raise AppliedStatementRevisionError(
            "link_existing is recorded by create_applied_statement_event"
        )
    accepted_at = _require_timestamp(applied_at or datetime.now(UTC), name="applied_at")
    fingerprint = _require_sha256(material_fingerprint, name="material_fingerprint")
    digest = _require_sha256(document_sha256, name="document_sha256")
    identity = _require_text(natural_identity, name="natural_identity")
    if identity != event.natural_identity:
        raise ValueError("revision must preserve logical statement event identity")
    event.account_id = account_id
    event.instrument_id = instrument_id
    event.event_kind = _coerce_kind(event_kind)
    event.isin = _require_text(isin, name="isin").upper()
    event.record_date = _require_date(record_date, name="record_date")
    event.material_fingerprint = fingerprint
    event.document_sha256 = digest
    event.updated_at = accepted_at
    revision = _append_revision_row(
        session,
        event=event,
        revision_kind=kind,
        document_sha256=digest,
        natural_identity=identity,
        material_fingerprint=fingerprint,
        account_id=account_id,
        instrument_id=instrument_id,
        event_kind=event.event_kind,
        isin=event.isin,
        record_date=event.record_date,
        event_date=_require_date(event_date, name="event_date"),
        quantity=quantity,
        per_unit=per_unit,
        gross_amount_kopecks=gross_amount_kopecks,
        gross_currency=gross_currency,
        tax_available=tax_available,
        tax_amount_kopecks=tax_amount_kopecks,
        tax_rate=tax_rate,
        net_amount_kopecks=net_amount_kopecks,
        net_currency=net_currency,
        applied_at=accepted_at,
    )
    session.flush()
    return revision
