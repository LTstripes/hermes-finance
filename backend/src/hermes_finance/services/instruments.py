from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.persistence import Instrument


class InstrumentNotFoundError(LookupError):
    pass


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
    session.delete(instrument)
    session.commit()
