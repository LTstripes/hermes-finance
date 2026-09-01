from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.persistence import Base, Instrument, InstrumentMarketMapping, ReportingMonth


class InstrumentNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class InstrumentCleanupReference:
    kind: str
    lifecycle: str
    count: int
    month_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstrumentCleanupDuplicate:
    instrument_id: int
    name: str
    basis: str


@dataclass(frozen=True, slots=True)
class InstrumentCleanupResult:
    instrument_id: int
    can_delete: bool
    status: str
    reason_code: str
    message: str
    references: tuple[InstrumentCleanupReference, ...]
    active_duplicates: tuple[InstrumentCleanupDuplicate, ...]


class InstrumentDeletionBlockedError(RuntimeError):
    code = "instrument_deletion_blocked"

    def __init__(self, cleanup: InstrumentCleanupResult | None = None) -> None:
        self.cleanup = cleanup
        message = (
            cleanup.message
            if cleanup is not None
            else "Нельзя удалить: инструмент используется в сохранённых финансовых данных."
        )
        super().__init__(message)


_REFERENCE_METADATA: dict[str, tuple[str, str]] = {
    "instrument_market_mappings": ("market_mapping", "provider"),
    "broker_identity_mappings": ("broker_mapping", "provider"),
    "position_snapshots": ("position", "month"),
    "investment_cash_flows": ("investment_cash_flow", "month"),
    "expected_cash_flows": ("expected_cash_flow", "month"),
    "applied_provider_payouts": ("provider_payout", "history"),
    "applied_statement_events": ("statement_event", "history"),
    "applied_statement_event_revisions": ("statement_history", "history"),
}
_REFERENCE_LABELS = {
    "market_mapping": "сопоставлением с источником котировок",
    "broker_mapping": "сопоставлением с брокером",
    "position": "позицией",
    "investment_cash_flow": "инвестиционным потоком",
    "expected_cash_flow": "ожидаемым денежным потоком",
    "provider_payout": "применённой выплатой провайдера",
    "statement_event": "импортированной выплатой из выписки",
    "statement_history": "историей импортированной выплаты",
    "other_reference": "сохранённой финансовой записью",
}
_MONTH_NAMES = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
_LIFECYCLE_ORDER = {"provider": 0, "historical": 1, "draft": 2}


def _coerce_instrument_type(instrument_type: InstrumentType | str) -> InstrumentType:
    try:
        return InstrumentType(instrument_type)
    except ValueError as error:
        raise ValueError(f"unsupported instrument type: {instrument_type!r}") from error


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("instrument name must not be empty")
    return normalized


def _normalize_optional_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_isin(isin: str | None) -> str | None:
    normalized = _normalize_optional_code(isin)
    return normalized.upper() if normalized is not None else None


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if not normalized:
        raise ValueError("currency must not be empty")
    return normalized


def _normalize_nominal_value(nominal_value: RubleAmount | None) -> int | None:
    if nominal_value is None:
        return None
    if nominal_value.kopecks < 0:
        raise ValueError("nominal_value must not be negative")
    return nominal_value.kopecks


def _month_label(year: int, month: int) -> str:
    if 1 <= month <= 12:
        return f"{_MONTH_NAMES[month - 1]} {year}"
    return f"{year:04d}-{month:02d}"


def _is_instrument_foreign_key(column: object) -> bool:
    foreign_keys = getattr(column, "foreign_keys", ())
    return any(
        foreign_key.column.table is Instrument.__table__ and foreign_key.column.name == "id"
        for foreign_key in foreign_keys
    )


def _reference_metadata(table_name: str) -> tuple[str, str]:
    return _REFERENCE_METADATA.get(table_name, ("other_reference", "history"))


def _collect_instrument_references(
    session: Session,
    instrument_id: int,
) -> tuple[InstrumentCleanupReference, ...]:
    counts: dict[tuple[str, str], int] = {}
    months: dict[tuple[str, str], set[str]] = {}

    def add_reference(
        *, kind: str, lifecycle: str, count: int, month_labels: tuple[str, ...] = ()
    ) -> None:
        if count <= 0:
            return
        key = (kind, lifecycle)
        counts[key] = counts.get(key, 0) + count
        months.setdefault(key, set()).update(month_labels)

    for table in Base.metadata.sorted_tables:
        if table is Instrument.__table__:
            continue
        instrument_columns = [
            column for column in table.columns if _is_instrument_foreign_key(column)
        ]
        if not instrument_columns:
            continue
        kind, mode = _reference_metadata(table.name)
        for column in instrument_columns:
            if "reporting_month_id" in table.c:
                month_id_column = table.c.reporting_month_id
                reference_count = func.count().label("reference_count")
                rows = session.execute(
                    select(
                        ReportingMonth.__table__.c.status,
                        ReportingMonth.__table__.c.year,
                        ReportingMonth.__table__.c.month,
                        reference_count,
                    )
                    .select_from(
                        table.join(
                            ReportingMonth.__table__,
                            month_id_column == ReportingMonth.__table__.c.id,
                        )
                    )
                    .where(column == instrument_id)
                    .group_by(
                        ReportingMonth.__table__.c.status,
                        ReportingMonth.__table__.c.year,
                        ReportingMonth.__table__.c.month,
                    )
                    .order_by(
                        ReportingMonth.__table__.c.year,
                        ReportingMonth.__table__.c.month,
                    )
                ).all()
                for row in rows:
                    mapping = row._mapping
                    lifecycle = (
                        "historical"
                        if mode == "history"
                        else ("draft" if mapping["status"] == "draft" else "historical")
                    )
                    add_reference(
                        kind=kind,
                        lifecycle=lifecycle,
                        count=int(mapping["reference_count"]),
                        month_labels=(_month_label(int(mapping["year"]), int(mapping["month"])),),
                    )
                continue

            count = session.scalar(
                select(func.count()).select_from(table).where(column == instrument_id)
            )
            lifecycle = "provider" if mode == "provider" else "historical"
            add_reference(kind=kind, lifecycle=lifecycle, count=int(count or 0))

    return tuple(
        InstrumentCleanupReference(
            kind=kind,
            lifecycle=lifecycle,
            count=counts[(kind, lifecycle)],
            month_labels=tuple(sorted(months.get((kind, lifecycle), set()))),
        )
        for kind, lifecycle in sorted(
            counts,
            key=lambda key: (_LIFECYCLE_ORDER.get(key[1], 99), key[0]),
        )
    )


def _active_duplicate_instruments(
    session: Session,
    instrument: Instrument,
) -> tuple[InstrumentCleanupDuplicate, ...]:
    matches: dict[int, tuple[str, set[str]]] = {}

    normalized_isin = _normalize_isin(instrument.isin)
    if normalized_isin is not None:
        isin_rows = session.execute(
            select(
                Instrument.id.label("instrument_id"),
                Instrument.name.label("instrument_name"),
            ).where(
                Instrument.id != instrument.id,
                Instrument.is_active.is_(True),
                func.upper(func.trim(Instrument.isin)) == normalized_isin,
            )
        ).all()
        for row in isin_rows:
            mapping = row._mapping
            matches[int(mapping["instrument_id"])] = (
                str(mapping["instrument_name"]),
                {"isin"},
            )

    mapping = session.get(InstrumentMarketMapping, instrument.id)
    if mapping is not None and mapping.provider and mapping.provider_instrument_id:
        identity_conditions = [
            func.upper(func.trim(InstrumentMarketMapping.provider))
            == mapping.provider.strip().upper(),
            func.upper(func.trim(InstrumentMarketMapping.provider_instrument_id))
            == mapping.provider_instrument_id.strip().upper(),
        ]
        if mapping.provider_venue_id is None:
            identity_conditions.append(InstrumentMarketMapping.provider_venue_id.is_(None))
        else:
            identity_conditions.append(
                func.upper(func.trim(InstrumentMarketMapping.provider_venue_id))
                == mapping.provider_venue_id.strip().upper()
            )
        mapping_rows = session.execute(
            select(
                Instrument.id.label("instrument_id"),
                Instrument.name.label("instrument_name"),
            )
            .join(InstrumentMarketMapping, InstrumentMarketMapping.instrument_id == Instrument.id)
            .where(
                Instrument.id != instrument.id,
                Instrument.is_active.is_(True),
                *identity_conditions,
            )
        ).all()
        for row in mapping_rows:
            mapping_row = row._mapping
            duplicate_id = int(mapping_row["instrument_id"])
            previous = matches.get(duplicate_id)
            if previous is None:
                matches[duplicate_id] = (str(mapping_row["instrument_name"]), {"market_mapping"})
            else:
                matches[duplicate_id] = (previous[0], previous[1] | {"market_mapping"})

    return tuple(
        InstrumentCleanupDuplicate(
            instrument_id=duplicate_id,
            name=name,
            basis="isin" if "isin" in bases else "market_mapping",
        )
        for duplicate_id, (name, bases) in sorted(matches.items())
    )


def _format_months(month_labels: tuple[str, ...]) -> str:
    if not month_labels:
        return ""
    if len(month_labels) == 1:
        return f"«{month_labels[0]}»"
    if len(month_labels) <= 3:
        return ", ".join(f"«{label}»" for label in month_labels[:-1]) + (f" и «{month_labels[-1]}»")
    return ", ".join(f"«{label}»" for label in month_labels[:3]) + f" и ещё {len(month_labels) - 3}"


def _reference_clause(reference: InstrumentCleanupReference) -> str:
    label = _REFERENCE_LABELS.get(reference.kind, _REFERENCE_LABELS["other_reference"])
    if reference.lifecycle == "provider":
        return f"инструмент связан с {label}"
    if reference.lifecycle == "draft":
        scope = _format_months(reference.month_labels)
        suffix = f" в черновике {scope}" if scope else " в текущем черновике"
        return f"инструмент используется{suffix} ({label})"
    scope = _format_months(reference.month_labels)
    suffix = f" в закрытой истории {scope}" if scope else " в сохранённой истории"
    return f"инструмент используется{suffix} ({label})"


def _reason_code(references: tuple[InstrumentCleanupReference, ...]) -> str:
    lifecycles = {reference.lifecycle for reference in references}
    if lifecycles == {"provider"}:
        return "provider_mapped"
    if lifecycles == {"historical"}:
        return "historical_referenced"
    if lifecycles == {"draft"}:
        return "draft_referenced"
    return "mixed_references"


def _duplicate_advisory(duplicates: tuple[InstrumentCleanupDuplicate, ...]) -> str:
    if not duplicates:
        return ""
    names = ", ".join(f"«{item.name}»" for item in duplicates[:3])
    if len(duplicates) > 3:
        names += f" и ещё {len(duplicates) - 3}"
    bases = {item.basis for item in duplicates}
    basis = "точным ISIN" if bases == {"isin"} else "принятым идентификатором источника"
    return (
        f" Найден активный инструмент {names} с тем же {basis}; автоматическое объединение "
        "не выполняется."
    )


def _cleanup_message(
    references: tuple[InstrumentCleanupReference, ...],
    duplicates: tuple[InstrumentCleanupDuplicate, ...],
) -> tuple[str, str]:
    if not references:
        message = "Инструмент не используется. Его можно удалить после явного подтверждения."
        if duplicates:
            message = "Это неиспользуемый дубликат. " + message
        return (
            "unused_duplicate" if duplicates else "unused",
            message + _duplicate_advisory(duplicates),
        )

    clauses = "; ".join(_reference_clause(reference) for reference in references)
    lifecycles = {reference.lifecycle for reference in references}
    if "provider" in lifecycles or "historical" in lifecycles:
        tail = "Сохранённые сопоставления и историю источника нельзя удалять автоматически или переписывать."
    else:
        tail = "Сначала удали или измени записи в черновике. Неактивность инструмента не отменяет эти ссылки."
    return (
        _reason_code(references),
        f"Нельзя удалить: {clauses}. {tail} Неактивность инструмента не удаляет эти данные."
        + _duplicate_advisory(duplicates),
    )


def _build_instrument_cleanup(
    session: Session,
    instrument: Instrument,
) -> InstrumentCleanupResult:
    references = _collect_instrument_references(session, instrument.id)
    duplicates = _active_duplicate_instruments(session, instrument)
    reason_code, message = _cleanup_message(references, duplicates)
    can_delete = not references
    return InstrumentCleanupResult(
        instrument_id=instrument.id,
        can_delete=can_delete,
        status="deletable" if can_delete else "protected",
        reason_code=reason_code,
        message=message,
        references=references,
        active_duplicates=duplicates,
    )


def get_instrument_cleanup(session: Session, instrument_id: int) -> InstrumentCleanupResult:
    return _build_instrument_cleanup(session, get_instrument(session, instrument_id))


def inspect_instrument_cleanup(session: Session, instrument_id: int) -> InstrumentCleanupResult:
    """Compatibility alias for callers that name the operation as an inspection."""

    return get_instrument_cleanup(session, instrument_id)


def list_instruments(session: Session) -> list[Instrument]:
    return list(session.scalars(select(Instrument).order_by(Instrument.name, Instrument.id)))


def get_instrument(session: Session, instrument_id: int) -> Instrument:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")
    return instrument


def get_instrument_by_isin(session: Session, isin: str) -> Instrument | None:
    return session.scalar(select(Instrument).where(Instrument.isin == isin.strip().upper()))


def create_instrument(
    session: Session,
    *,
    name: str,
    instrument_type: InstrumentType | str,
    isin: str | None = None,
    ticker: str | None = None,
    moex_secid: str | None = None,
    currency: str = "RUB",
    nominal_value: RubleAmount | None = None,
    is_active: bool = True,
    manual_price_allowed: bool = True,
    notes: str | None = None,
) -> Instrument:
    instrument = Instrument(
        name=_normalize_name(name),
        instrument_type=_coerce_instrument_type(instrument_type).value,
        isin=_normalize_isin(isin),
        ticker=_normalize_optional_code(ticker),
        moex_secid=_normalize_optional_code(moex_secid),
        currency=_normalize_currency(currency),
        nominal_value_kopecks=_normalize_nominal_value(nominal_value),
        is_active=is_active,
        manual_price_allowed=manual_price_allowed,
        notes=notes,
    )
    session.add(instrument)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("isin must be unique when provided") from error
    session.refresh(instrument)
    return instrument


def update_instrument(
    session: Session,
    instrument_id: int,
    *,
    name: str | None = None,
    instrument_type: InstrumentType | str | None = None,
    isin: str | None = None,
    ticker: str | None = None,
    moex_secid: str | None = None,
    currency: str | None = None,
    nominal_value: RubleAmount | None = None,
    is_active: bool | None = None,
    manual_price_allowed: bool | None = None,
    notes: str | None = None,
) -> Instrument:
    instrument = get_instrument(session, instrument_id)
    if name is not None:
        instrument.name = _normalize_name(name)
    if instrument_type is not None:
        instrument.instrument_type = _coerce_instrument_type(instrument_type).value
    if isin is not None:
        instrument.isin = _normalize_isin(isin)
    if ticker is not None:
        instrument.ticker = _normalize_optional_code(ticker)
    if moex_secid is not None:
        instrument.moex_secid = _normalize_optional_code(moex_secid)
    if currency is not None:
        instrument.currency = _normalize_currency(currency)
    if nominal_value is not None:
        instrument.nominal_value_kopecks = _normalize_nominal_value(nominal_value)
    if is_active is not None:
        instrument.is_active = is_active
    if manual_price_allowed is not None:
        instrument.manual_price_allowed = manual_price_allowed
    if notes is not None:
        instrument.notes = notes

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("isin must be unique when provided") from error
    session.refresh(instrument)
    return instrument


def delete_instrument(session: Session, instrument_id: int) -> None:
    instrument = get_instrument(session, instrument_id)
    cleanup = _build_instrument_cleanup(session, instrument)
    if not cleanup.can_delete:
        raise InstrumentDeletionBlockedError(cleanup)
    session.delete(instrument)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        fallback = InstrumentCleanupResult(
            instrument_id=instrument_id,
            can_delete=False,
            status="protected",
            reason_code="reference_changed",
            message=(
                "Нельзя удалить: инструмент всё ещё используется в сохранённых финансовых "
                "данных. Обнови проверку и повтори попытку."
            ),
            references=(),
            active_duplicates=(),
        )
        raise InstrumentDeletionBlockedError(fallback) from error
