"""Pure provider-neutral identity matching for reconciliation (R06-04).

Only explicit owner mapping or an exact, unique normalized ISIN match may
resolve an instrument identity. Account identity is resolved ONLY by explicit
owner mapping. No inference from names, IIAType, ticker, section codes,
ordering or numeric similarity. No silent remap on provider id change.

ISIN normalization follows existing Hermes semantics (services/instruments.py):
strip() + upper(). Empty/whitespace-only ISIN is treated as absent.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from hermes_finance.broker_data.dto import BrokerSnapshot
from hermes_finance.broker_data.reconciliation.dto import (
    AccountMatchStatus,
    AccountObservedInstrument,
    AccountReconciliationRow,
    HermesInstrumentView,
    HermesStateView,
    InstrumentMatchStatus,
    InstrumentReconciliationRow,
    OwnerMappingInput,
)


def _unique_nonempty(values: Iterable[str | None]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _account_identity(
    snapshot: BrokerSnapshot, provider_account_id: str
) -> tuple[tuple[str, ...], tuple[AccountObservedInstrument, ...]]:
    """Collect accepted snapshot observations for owner display only."""

    section_codes = _unique_nonempty(
        section.section_code
        for section in snapshot.sections
        if section.provider_account_id == provider_account_id
    )
    observed: list[AccountObservedInstrument] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for position in snapshot.positions:
        if position.provider_account_id != provider_account_id:
            continue
        item = AccountObservedInstrument(
            display_name=position.display_name or None,
            isin=_normalize_isin(position.isin),
            ticker=position.ticker or None,
        )
        if item.display_name is None and item.isin is None and item.ticker is None:
            continue
        key = (item.display_name, item.isin, item.ticker)
        if key in seen:
            continue
        seen.add(key)
        observed.append(item)
    return section_codes, tuple(observed)


def _account_row(
    *,
    provider_account_id: str,
    hermes_account_id: int | None,
    status: AccountMatchStatus,
    reason: str | None,
    section_codes: tuple[str, ...],
    observed_instruments: tuple[AccountObservedInstrument, ...],
) -> AccountReconciliationRow:
    return AccountReconciliationRow(
        provider_account_id=provider_account_id,
        hermes_account_id=hermes_account_id,
        status=status,
        reason=reason,
        section_codes=section_codes,
        observed_instruments=observed_instruments,
    )


def _normalize_isin(isin: str | None) -> str | None:
    """Canonical Hermes ISIN normalization: strip() + upper().

    Mirrors services/instruments.py _normalize_isin. Empty/whitespace-only ISIN
    becomes None (absent) so it can never match or synthesize identity.
    """
    if not isin:
        return None
    normalized = isin.strip().upper()
    return normalized or None


def _account_map(
    mapping: OwnerMappingInput,
) -> tuple[dict[str, int], set[str]]:
    """provider_account_id -> hermes_account_id (first wins) + conflict set.

    A provider account id mapped to two different Hermes account ids is a hard
    conflict (fail-closed), never last-wins. Identical repeated pairs are
    idempotent. Tuple element order does not change the result.
    """
    resolved: dict[str, int] = {}
    conflicting: set[str] = set()
    for entry in mapping.accounts:
        pid = entry.provider_account_id
        hid = entry.hermes_account_id
        if pid in resolved:
            if resolved[pid] != hid:
                conflicting.add(pid)
        else:
            resolved[pid] = hid
    return resolved, conflicting


def _instrument_explicit_map(
    mapping: OwnerMappingInput,
) -> tuple[dict[str, int], set[str]]:
    """provider_instrument_id -> hermes_instrument_id (first wins) + conflict set."""
    resolved: dict[str, int] = {}
    conflicting: set[str] = set()
    for entry in mapping.instruments:
        pid = entry.provider_instrument_id
        hid = entry.hermes_instrument_id
        if pid in resolved:
            if resolved[pid] != hid:
                conflicting.add(pid)
        else:
            resolved[pid] = hid
    return resolved, conflicting


def _hermes_isin_by_id(hermes: HermesStateView) -> dict[int, str | None]:
    return {inst.instrument_id: _normalize_isin(inst.isin) for inst in hermes.instruments}


def reconcile_accounts(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
) -> tuple[AccountReconciliationRow, ...]:
    explicit, conflicting = _account_map(mapping)
    hermes_ids = {acc.account_id for acc in hermes.accounts}
    rows: list[AccountReconciliationRow] = []

    seen_providers: set[str] = set()
    for account in snapshot.accounts:
        pid = account.provider_account_id
        first_seen = pid not in seen_providers
        seen_providers.add(pid)
        section_codes, observed_instruments = _account_identity(snapshot, pid)

        if pid in conflicting:
            rows.append(
                _account_row(
                    provider_account_id=pid,
                    hermes_account_id=None,
                    status=AccountMatchStatus.CONFLICT,
                    reason=(
                        "conflicting explicit owner mapping: provider account id "
                        "mapped to multiple Hermes accounts"
                    ),
                    section_codes=section_codes,
                    observed_instruments=observed_instruments,
                )
            )
            continue
        if not first_seen:
            rows.append(
                _account_row(
                    provider_account_id=pid,
                    hermes_account_id=None,
                    status=AccountMatchStatus.CONFLICT,
                    reason="duplicate provider account identifier in snapshot",
                    section_codes=section_codes,
                    observed_instruments=observed_instruments,
                )
            )
            continue
        if pid in explicit:
            hid = explicit[pid]
            if hid in hermes_ids:
                rows.append(
                    _account_row(
                        provider_account_id=pid,
                        hermes_account_id=hid,
                        status=AccountMatchStatus.MATCHED,
                        reason=None,
                        section_codes=section_codes,
                        observed_instruments=observed_instruments,
                    )
                )
            else:
                rows.append(
                    _account_row(
                        provider_account_id=pid,
                        hermes_account_id=hid,
                        status=AccountMatchStatus.CONFLICT,
                        reason="explicit mapping targets a Hermes account id that does not exist",
                        section_codes=section_codes,
                        observed_instruments=observed_instruments,
                    )
                )
        else:
            rows.append(
                _account_row(
                    provider_account_id=pid,
                    hermes_account_id=None,
                    status=AccountMatchStatus.UNMATCHED,
                    reason="no explicit owner mapping for provider account",
                    section_codes=section_codes,
                    observed_instruments=observed_instruments,
                )
            )
    return tuple(rows)


def _isin_index(
    hermes: HermesStateView,
) -> dict[str, list[HermesInstrumentView]]:
    index: dict[str, list[HermesInstrumentView]] = defaultdict(list)
    for inst in hermes.instruments:
        norm = _normalize_isin(inst.isin)
        if norm:
            index[norm].append(inst)
    return index


def _resolve_instrument(
    *,
    pid: str | None,
    isin: str | None,
    ticker: str | None,
    display_name: str | None,
    explicit: dict[str, int],
    conflicting: set[str],
    isin_index: dict[str, list[HermesInstrumentView]],
    hermes_ids: set[int],
    hermes_isin_by_id: dict[int, str | None],
) -> tuple[int | None, InstrumentMatchStatus, str | None]:
    if pid is not None and pid in conflicting:
        return (
            None,
            InstrumentMatchStatus.CONFLICT,
            "conflicting explicit owner mapping: provider instrument id mapped to "
            "multiple Hermes instruments",
        )
    if pid is not None and pid in explicit:
        hid = explicit[pid]
        if hid in hermes_ids:
            # B5: explicit mapping must not silently override contradictory ISIN
            # evidence. Fail closed only when both ISINs are present and differ.
            norm = _normalize_isin(isin)
            hermes_isin = hermes_isin_by_id.get(hid)
            if norm is not None and hermes_isin is not None and norm != hermes_isin:
                return (
                    hid,
                    InstrumentMatchStatus.CONFLICT,
                    "explicit mapping contradicts provider ISIN evidence",
                )
            return hid, InstrumentMatchStatus.MATCHED, "explicit owner mapping"
        return (
            hid,
            InstrumentMatchStatus.CONFLICT,
            "explicit mapping targets a Hermes instrument id that does not exist",
        )

    norm = _normalize_isin(isin)
    if norm:
        matches = isin_index.get(norm, [])
        if len(matches) == 1:
            return (
                matches[0].instrument_id,
                InstrumentMatchStatus.MATCHED,
                "exact unique ISIN match",
            )
        if len(matches) > 1:
            return (
                None,
                InstrumentMatchStatus.AMBIGUOUS,
                "multiple Hermes instruments share this ISIN",
            )
        return (
            None,
            InstrumentMatchStatus.UNMATCHED,
            "no Hermes instrument with this ISIN",
        )
    return (
        None,
        InstrumentMatchStatus.UNMATCHED,
        "no ISIN and no explicit mapping; ticker/name/provider id are not identity",
    )


def reconcile_instruments(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
) -> tuple[InstrumentReconciliationRow, ...]:
    explicit, conflicting = _instrument_explicit_map(mapping)
    isin_index = _isin_index(hermes)
    hermes_ids = {inst.instrument_id for inst in hermes.instruments}
    hermes_isin_by_id = _hermes_isin_by_id(hermes)
    rows: list[InstrumentReconciliationRow] = []

    seen_providers: set[str] = set()
    resolved_pid: dict[str | None, int | None] = {}
    for pos in snapshot.positions:
        pid = pos.provider_instrument_id
        hid, status, reason = _resolve_instrument(
            pid=pid,
            isin=pos.isin,
            ticker=pos.ticker,
            display_name=pos.display_name,
            explicit=explicit,
            conflicting=conflicting,
            isin_index=isin_index,
            hermes_ids=hermes_ids,
            hermes_isin_by_id=hermes_isin_by_id,
        )
        if pid in seen_providers:
            # B4: repeating provider id across accounts is NOT an instrument
            # conflict. Only a contradiction of resolved identity fails closed.
            if resolved_pid.get(pid) != hid:
                rows.append(
                    InstrumentReconciliationRow(
                        provider_instrument_id=pid,
                        isin=_normalize_isin(pos.isin),
                        ticker=pos.ticker,
                        display_name=pos.display_name,
                        hermes_instrument_id=None,
                        status=InstrumentMatchStatus.CONFLICT,
                        reason="conflicting metadata for the same provider instrument identifier",
                    )
                )
            continue
        seen_providers.add(pid)
        resolved_pid[pid] = hid
        rows.append(
            InstrumentReconciliationRow(
                provider_instrument_id=pid,
                isin=_normalize_isin(pos.isin),
                ticker=pos.ticker,
                display_name=pos.display_name,
                hermes_instrument_id=hid,
                status=status,
                reason=reason,
            )
        )
    return tuple(rows)
