"""Persistent broker identity mapping registry (ADR 0016 Slice A).

Explicit confirm / revoke / remap only. Unique ISIN matching does not write.
No backfill from market mappings, statements, names, tickers or IIAType.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.broker_data.dto import BrokerSnapshot
from hermes_finance.broker_data.reconciliation.dto import (
    AccountMappingInput,
    AccountMatchStatus,
    AccountReconciliationRow,
    InstrumentMappingInput,
    InstrumentMatchStatus,
    InstrumentReconciliationRow,
    OwnerMappingInput,
)
from hermes_finance.persistence import Account, BrokerIdentityMapping, Instrument
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.instruments import InstrumentNotFoundError


class BrokerIdentitySubjectKind(StrEnum):
    ACCOUNT = "account"
    INSTRUMENT = "instrument"


class BrokerIdentityMappingStatus(StrEnum):
    EFFECTIVE = "effective"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class IdentityClassification(StrEnum):
    REUSED = "reused"
    DETERMINISTIC_ISIN = "deterministic_isin"
    EXPLICIT = "explicit"
    NEW = "new"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    PROVIDER_IDENTITY_ABSENT = "provider_identity_absent"


class BrokerIdentityMappingConflictError(ValueError):
    """Fail-closed uniqueness or request/registry disagreement."""


class BrokerIdentityMappingNotFoundError(LookupError):
    pass


_EXPLICIT_REASON = "explicit owner mapping"
_ISIN_REASON = "exact unique ISIN match"
_ABSENT_REASON = "effective mapping provider identity is not in this snapshot"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_token(value: str, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")
    return normalized


def _normalize_isin(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("observed_isin must be a string")
    normalized = value.strip().upper()
    if not normalized:
        return None
    if len(normalized) > 12:
        raise ValueError("observed_isin must be at most 12 characters")
    return normalized


def _normalize_kind(value: BrokerIdentitySubjectKind | str) -> BrokerIdentitySubjectKind:
    try:
        return BrokerIdentitySubjectKind(value)
    except ValueError as error:
        raise ValueError(f"unsupported mapping subject_kind: {value!r}") from error


def _optional_reason(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 256:
        raise ValueError("revoke_reason must be at most 256 characters")
    return normalized


def list_mappings(session: Session, *, provider: str | None = None) -> list[BrokerIdentityMapping]:
    statement = select(BrokerIdentityMapping).order_by(BrokerIdentityMapping.id)
    if provider is not None:
        provider_name = _normalize_token(provider, field="provider", max_length=32)
        statement = statement.where(BrokerIdentityMapping.provider == provider_name)
    return list(session.scalars(statement))


def list_effective_mappings(session: Session, *, provider: str) -> list[BrokerIdentityMapping]:
    normalized = _normalize_token(provider, field="provider", max_length=32)
    return list(
        session.scalars(
            select(BrokerIdentityMapping)
            .where(BrokerIdentityMapping.provider == normalized)
            .where(BrokerIdentityMapping.status == BrokerIdentityMappingStatus.EFFECTIVE.value)
            .order_by(BrokerIdentityMapping.id)
        )
    )


def get_mapping(session: Session, mapping_id: int) -> BrokerIdentityMapping:
    row = session.get(BrokerIdentityMapping, mapping_id)
    if row is None:
        raise BrokerIdentityMappingNotFoundError(
            f"broker identity mapping {mapping_id} was not found"
        )
    return row


def _effective_for_identity(
    session: Session,
    *,
    provider: str,
    subject_kind: BrokerIdentitySubjectKind,
    provider_identity: str,
) -> BrokerIdentityMapping | None:
    return session.scalar(
        select(BrokerIdentityMapping)
        .where(BrokerIdentityMapping.provider == provider)
        .where(BrokerIdentityMapping.subject_kind == subject_kind.value)
        .where(BrokerIdentityMapping.provider_identity == provider_identity)
        .where(BrokerIdentityMapping.status == BrokerIdentityMappingStatus.EFFECTIVE.value)
    )


def _effective_instrument_for_hermes(
    session: Session, *, provider: str, hermes_instrument_id: int
) -> BrokerIdentityMapping | None:
    return session.scalar(
        select(BrokerIdentityMapping)
        .where(BrokerIdentityMapping.provider == provider)
        .where(BrokerIdentityMapping.subject_kind == BrokerIdentitySubjectKind.INSTRUMENT.value)
        .where(BrokerIdentityMapping.hermes_instrument_id == hermes_instrument_id)
        .where(BrokerIdentityMapping.status == BrokerIdentityMappingStatus.EFFECTIVE.value)
    )


def _require_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def _require_instrument(session: Session, instrument_id: int) -> Instrument:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")
    return instrument


def _reject_instrument_isin_conflict(instrument: Instrument, observed_isin: str | None) -> None:
    if observed_isin is None or instrument.isin is None:
        return
    if instrument.isin != observed_isin:
        raise BrokerIdentityMappingConflictError(
            "explicit mapping contradicts provider ISIN evidence"
        )


def confirm_mapping(
    session: Session,
    *,
    provider: str,
    subject_kind: BrokerIdentitySubjectKind | str,
    provider_identity: str,
    hermes_target_id: int,
    observed_isin: str | None = None,
    source_as_of: datetime | None = None,
    captured_at: datetime | None = None,
    commit: bool = True,
) -> BrokerIdentityMapping:
    provider_name = _normalize_token(provider, field="provider", max_length=32)
    kind = _normalize_kind(subject_kind)
    identity = _normalize_token(provider_identity, field="provider_identity", max_length=128)
    if (
        isinstance(hermes_target_id, bool)
        or not isinstance(hermes_target_id, int)
        or hermes_target_id <= 0
    ):
        raise ValueError("hermes_target_id must be a positive integer")
    isin = _normalize_isin(observed_isin)
    if kind is BrokerIdentitySubjectKind.ACCOUNT and isin is not None:
        raise ValueError("observed_isin is only valid for instrument mappings")

    existing = _effective_for_identity(
        session, provider=provider_name, subject_kind=kind, provider_identity=identity
    )
    if existing is not None:
        if existing.hermes_target_id != hermes_target_id:
            raise BrokerIdentityMappingConflictError(
                "provider identity already has an effective mapping to a different Hermes target"
            )
        if kind is BrokerIdentitySubjectKind.INSTRUMENT:
            instrument = _require_instrument(session, hermes_target_id)
            _reject_instrument_isin_conflict(instrument, isin)
        return existing

    account_id: int | None = None
    instrument_id: int | None = None
    if kind is BrokerIdentitySubjectKind.ACCOUNT:
        _require_account(session, hermes_target_id)
        account_id = hermes_target_id
    else:
        instrument = _require_instrument(session, hermes_target_id)
        _reject_instrument_isin_conflict(instrument, isin)
        reverse = _effective_instrument_for_hermes(
            session, provider=provider_name, hermes_instrument_id=hermes_target_id
        )
        if reverse is not None:
            raise BrokerIdentityMappingConflictError(
                "Hermes instrument already has an effective mapping from a different provider identity"
            )
        instrument_id = hermes_target_id

    row = BrokerIdentityMapping(
        provider=provider_name,
        subject_kind=kind.value,
        provider_identity=identity,
        hermes_account_id=account_id,
        hermes_instrument_id=instrument_id,
        status=BrokerIdentityMappingStatus.EFFECTIVE.value,
        observed_isin=isin,
        confirmed_at=_utcnow(),
        source_as_of=source_as_of,
        captured_at=captured_at,
    )
    session.add(row)
    session.flush()
    if commit:
        session.commit()
        session.refresh(row)
    return row


def revoke_mapping(
    session: Session,
    mapping_id: int,
    *,
    reason: str | None = None,
) -> BrokerIdentityMapping:
    row = get_mapping(session, mapping_id)
    revoke_reason = _optional_reason(reason)
    if row.status == BrokerIdentityMappingStatus.REVOKED.value:
        return row
    if row.status != BrokerIdentityMappingStatus.EFFECTIVE.value:
        raise BrokerIdentityMappingConflictError("only an effective mapping can be revoked")
    row.status = BrokerIdentityMappingStatus.REVOKED.value
    row.revoked_at = _utcnow()
    row.revoke_reason = revoke_reason
    session.commit()
    session.refresh(row)
    return row


def remap_mapping(
    session: Session,
    mapping_id: int,
    *,
    hermes_target_id: int,
    observed_isin: str | None = None,
    source_as_of: datetime | None = None,
    captured_at: datetime | None = None,
) -> BrokerIdentityMapping:
    current = get_mapping(session, mapping_id)
    if current.status != BrokerIdentityMappingStatus.EFFECTIVE.value:
        raise BrokerIdentityMappingConflictError("only an effective mapping can be remapped")
    if (
        isinstance(hermes_target_id, bool)
        or not isinstance(hermes_target_id, int)
        or hermes_target_id <= 0
    ):
        raise ValueError("hermes_target_id must be a positive integer")
    isin = _normalize_isin(observed_isin)
    kind = BrokerIdentitySubjectKind(current.subject_kind)
    if kind is BrokerIdentitySubjectKind.ACCOUNT and isin is not None:
        raise ValueError("observed_isin is only valid for instrument mappings")
    if current.hermes_target_id == hermes_target_id:
        if kind is BrokerIdentitySubjectKind.INSTRUMENT:
            instrument = _require_instrument(session, hermes_target_id)
            _reject_instrument_isin_conflict(instrument, isin)
        return current

    account_id: int | None = None
    instrument_id: int | None = None
    if kind is BrokerIdentitySubjectKind.ACCOUNT:
        _require_account(session, hermes_target_id)
        account_id = hermes_target_id
    else:
        instrument = _require_instrument(session, hermes_target_id)
        _reject_instrument_isin_conflict(instrument, isin)
        reverse = _effective_instrument_for_hermes(
            session, provider=current.provider, hermes_instrument_id=hermes_target_id
        )
        if reverse is not None and reverse.id != current.id:
            raise BrokerIdentityMappingConflictError(
                "Hermes instrument already has an effective mapping from a different provider identity"
            )
        instrument_id = hermes_target_id

    replacement = BrokerIdentityMapping(
        provider=current.provider,
        subject_kind=current.subject_kind,
        provider_identity=current.provider_identity,
        hermes_account_id=account_id,
        hermes_instrument_id=instrument_id,
        status=BrokerIdentityMappingStatus.EFFECTIVE.value,
        observed_isin=isin,
        confirmed_at=_utcnow(),
        source_as_of=source_as_of,
        captured_at=captured_at,
        predecessor_mapping_id=current.id,
    )
    # Release partial unique indexes before inserting the successor effective row.
    current.status = BrokerIdentityMappingStatus.REVOKED.value
    current.revoked_at = _utcnow()
    session.flush()
    session.add(replacement)
    session.flush()
    current.status = BrokerIdentityMappingStatus.SUPERSEDED.value
    current.revoked_at = None
    current.revoke_reason = None
    current.successor_mapping_id = replacement.id
    session.commit()
    session.refresh(replacement)
    session.refresh(current)
    return replacement


def compose_owner_mapping(
    session: Session,
    *,
    provider: str,
    request: OwnerMappingInput,
) -> OwnerMappingInput:
    """Concatenate effective registry rows with the request mapping.

    Identical repeats are idempotent in the existing matcher. Distinct Hermes
    targets for one provider identity become matcher conflicts (fail-closed).
    """

    if not provider or not str(provider).strip():
        return request
    effective = list_effective_mappings(session, provider=provider)
    accounts = [
        AccountMappingInput(
            hermes_account_id=row.hermes_target_id,
            provider_account_id=row.provider_identity,
        )
        for row in effective
        if row.subject_kind == BrokerIdentitySubjectKind.ACCOUNT.value
    ]
    instruments = [
        InstrumentMappingInput(
            hermes_instrument_id=row.hermes_target_id,
            provider_instrument_id=row.provider_identity,
        )
        for row in effective
        if row.subject_kind == BrokerIdentitySubjectKind.INSTRUMENT.value
    ]
    return OwnerMappingInput(
        accounts=(*accounts, *request.accounts),
        instruments=(*instruments, *request.instruments),
    )


@dataclass(frozen=True, slots=True)
class PreviewIdentityLabels:
    accounts: dict[str, IdentityClassification]
    instruments: dict[str, IdentityClassification]
    absent_accounts: tuple[AccountReconciliationRow, ...]
    absent_instruments: tuple[InstrumentReconciliationRow, ...]


def _request_account_map(request: OwnerMappingInput) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for item in request.accounts:
        previous = resolved.get(item.provider_account_id)
        if previous is not None and previous != item.hermes_account_id:
            resolved[item.provider_account_id] = previous
            continue
        resolved[item.provider_account_id] = item.hermes_account_id
    return resolved


def _request_instrument_map(request: OwnerMappingInput) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for item in request.instruments:
        previous = resolved.get(item.provider_instrument_id)
        if previous is not None and previous != item.hermes_instrument_id:
            resolved[item.provider_instrument_id] = previous
            continue
        resolved[item.provider_instrument_id] = item.hermes_instrument_id
    return resolved


def classify_preview_identities(
    *,
    snapshot: BrokerSnapshot,
    account_rows: tuple[AccountReconciliationRow, ...],
    instrument_rows: tuple[InstrumentReconciliationRow, ...],
    session: Session,
    request: OwnerMappingInput,
) -> PreviewIdentityLabels:
    effective_rows = list_effective_mappings(session, provider=snapshot.provider)
    effective_accounts = {
        row.provider_identity: row.hermes_target_id
        for row in effective_rows
        if row.subject_kind == BrokerIdentitySubjectKind.ACCOUNT.value
    }
    effective_instruments = {
        row.provider_identity: row.hermes_target_id
        for row in effective_rows
        if row.subject_kind == BrokerIdentitySubjectKind.INSTRUMENT.value
    }
    request_accounts = _request_account_map(request)
    request_instruments = _request_instrument_map(request)
    snapshot_account_ids = {account.provider_account_id for account in snapshot.accounts}
    snapshot_instrument_ids = {
        position.provider_instrument_id
        for position in snapshot.positions
        if position.provider_instrument_id
    }

    account_labels: dict[str, IdentityClassification] = {}
    for row in account_rows:
        account_labels[row.provider_account_id] = _classify_account(
            row,
            effective=effective_accounts,
            request=request_accounts,
            snapshot_ids=snapshot_account_ids,
        )

    instrument_labels: dict[str, IdentityClassification] = {}
    for row in instrument_rows:
        if row.provider_instrument_id is None:
            continue
        instrument_labels[row.provider_instrument_id] = _classify_instrument(
            row,
            effective=effective_instruments,
            request=request_instruments,
            snapshot_ids=snapshot_instrument_ids,
        )

    absent_accounts: list[AccountReconciliationRow] = []
    for row in effective_rows:
        if row.subject_kind != BrokerIdentitySubjectKind.ACCOUNT.value:
            continue
        if row.provider_identity in snapshot_account_ids:
            continue
        absent_accounts.append(
            AccountReconciliationRow(
                provider_account_id=row.provider_identity,
                hermes_account_id=row.hermes_target_id,
                status=AccountMatchStatus.UNMATCHED,
                reason=_ABSENT_REASON,
            )
        )
        account_labels[row.provider_identity] = IdentityClassification.PROVIDER_IDENTITY_ABSENT

    absent_instruments: list[InstrumentReconciliationRow] = []
    for row in effective_rows:
        if row.subject_kind != BrokerIdentitySubjectKind.INSTRUMENT.value:
            continue
        if row.provider_identity in snapshot_instrument_ids:
            continue
        absent_instruments.append(
            InstrumentReconciliationRow(
                provider_instrument_id=row.provider_identity,
                isin=row.observed_isin,
                ticker=None,
                display_name=None,
                hermes_instrument_id=row.hermes_target_id,
                status=InstrumentMatchStatus.UNMATCHED,
                reason=_ABSENT_REASON,
            )
        )
        instrument_labels[row.provider_identity] = IdentityClassification.PROVIDER_IDENTITY_ABSENT

    return PreviewIdentityLabels(
        accounts=account_labels,
        instruments=instrument_labels,
        absent_accounts=tuple(absent_accounts),
        absent_instruments=tuple(absent_instruments),
    )


def _classify_account(
    row: AccountReconciliationRow,
    *,
    effective: dict[str, int],
    request: dict[str, int],
    snapshot_ids: set[str],
) -> IdentityClassification:
    pid = row.provider_account_id
    registry_target = effective.get(pid)
    request_target = request.get(pid)
    if (
        request_target is not None
        and registry_target is not None
        and request_target != registry_target
    ):
        return IdentityClassification.CONFLICT
    if row.status is AccountMatchStatus.CONFLICT:
        return IdentityClassification.CONFLICT
    if pid in effective and pid not in snapshot_ids:
        return IdentityClassification.PROVIDER_IDENTITY_ABSENT
    if row.status is AccountMatchStatus.MATCHED:
        if registry_target is not None and registry_target == row.hermes_account_id:
            return IdentityClassification.REUSED
        return IdentityClassification.EXPLICIT
    return IdentityClassification.NEW


def _classify_instrument(
    row: InstrumentReconciliationRow,
    *,
    effective: dict[str, int],
    request: dict[str, int],
    snapshot_ids: set[str],
) -> IdentityClassification:
    pid = row.provider_instrument_id
    if pid is None:
        if row.status is InstrumentMatchStatus.AMBIGUOUS:
            return IdentityClassification.AMBIGUOUS
        if row.status is InstrumentMatchStatus.CONFLICT:
            return IdentityClassification.CONFLICT
        if row.status is InstrumentMatchStatus.MATCHED and row.reason == _ISIN_REASON:
            return IdentityClassification.DETERMINISTIC_ISIN
        if row.status is InstrumentMatchStatus.MATCHED:
            return IdentityClassification.EXPLICIT
        return IdentityClassification.NEW
    registry_target = effective.get(pid)
    request_target = request.get(pid)
    if (
        request_target is not None
        and registry_target is not None
        and request_target != registry_target
    ):
        return IdentityClassification.CONFLICT
    if row.status is InstrumentMatchStatus.CONFLICT:
        return IdentityClassification.CONFLICT
    if row.status is InstrumentMatchStatus.AMBIGUOUS:
        return IdentityClassification.AMBIGUOUS
    if pid in effective and pid not in snapshot_ids:
        return IdentityClassification.PROVIDER_IDENTITY_ABSENT
    if row.status is InstrumentMatchStatus.MATCHED:
        if registry_target is not None and registry_target == row.hermes_instrument_id:
            return IdentityClassification.REUSED
        if row.reason == _ISIN_REASON:
            return IdentityClassification.DETERMINISTIC_ISIN
        return IdentityClassification.EXPLICIT
    return IdentityClassification.NEW
