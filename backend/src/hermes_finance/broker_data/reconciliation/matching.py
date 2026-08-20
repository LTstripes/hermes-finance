"""Pure provider-neutral identity matching for reconciliation (R06-04).

Only explicit owner mapping or an exact, unique ISIN match may resolve an
instrument identity. Account identity is resolved ONLY by explicit owner
mapping. No inference from names, IIAType, ticker, section codes, ordering or
numeric similarity. No silent remap on provider id change.
"""

from __future__ import annotations

from collections import defaultdict

from hermes_finance.broker_data.dto import BrokerSnapshot
from hermes_finance.broker_data.reconciliation.dto import (
    AccountMatchStatus,
    AccountReconciliationRow,
    HermesInstrumentView,
    HermesStateView,
    InstrumentMatchStatus,
    InstrumentReconciliationRow,
    OwnerMappingInput,
)


def _account_map(mapping: OwnerMappingInput) -> dict[str, int]:
    result: dict[str, int] = {}
    for entry in mapping.accounts:
        # Last explicit owner input wins; duplicates are an owner mistake, not a
        # reason to infer anything. Keep deterministic order by using the dict.
        result[entry.provider_account_id] = entry.hermes_account_id
    return result


def _instrument_explicit_map(mapping: OwnerMappingInput) -> dict[str, int]:
    result: dict[str, int] = {}
    for entry in mapping.instruments:
        result[entry.provider_instrument_id] = entry.hermes_instrument_id
    return result


def reconcile_accounts(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
) -> tuple[AccountReconciliationRow, ...]:
    explicit = _account_map(mapping)
    hermes_ids = {acc.account_id for acc in hermes.accounts}
    rows: list[AccountReconciliationRow] = []

    seen_providers: set[str] = set()
    for account in snapshot.accounts:
        pid = account.provider_account_id
        if pid in seen_providers:
            # Duplicate provider account id in the snapshot itself.
            rows.append(
                AccountReconciliationRow(
                    provider_account_id=pid,
                    hermes_account_id=None,
                    status=AccountMatchStatus.CONFLICT,
                    reason="duplicate provider account identifier in snapshot",
                )
            )
            continue
        seen_providers.add(pid)
        if pid in explicit:
            hid = explicit[pid]
            if hid in hermes_ids:
                rows.append(
                    AccountReconciliationRow(
                        provider_account_id=pid,
                        hermes_account_id=hid,
                        status=AccountMatchStatus.MATCHED,
                        reason=None,
                    )
                )
            else:
                rows.append(
                    AccountReconciliationRow(
                        provider_account_id=pid,
                        hermes_account_id=hid,
                        status=AccountMatchStatus.CONFLICT,
                        reason="explicit mapping targets a Hermes account id that does not exist",
                    )
                )
        else:
            rows.append(
                AccountReconciliationRow(
                    provider_account_id=pid,
                    hermes_account_id=None,
                    status=AccountMatchStatus.UNMATCHED,
                    reason="no explicit owner mapping for provider account",
                )
            )
    return tuple(rows)


def _isin_index(hermes: HermesStateView) -> dict[str, list[HermesInstrumentView]]:
    index: dict[str, list[HermesInstrumentView]] = defaultdict(list)
    for inst in hermes.instruments:
        if inst.isin:
            index[inst.isin].append(inst)
    return index


def reconcile_instruments(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
) -> tuple[InstrumentReconciliationRow, ...]:
    explicit = _instrument_explicit_map(mapping)
    isin_index = _isin_index(hermes)
    hermes_ids = {inst.instrument_id for inst in hermes.instruments}
    rows: list[InstrumentReconciliationRow] = []

    seen_providers: set[str] = set()
    for pos in snapshot.positions:
        pid = pos.provider_instrument_id
        if pid in seen_providers:
            rows.append(
                InstrumentReconciliationRow(
                    provider_instrument_id=pid,
                    isin=pos.isin,
                    ticker=pos.ticker,
                    display_name=pos.display_name,
                    hermes_instrument_id=None,
                    status=InstrumentMatchStatus.CONFLICT,
                    reason="duplicate provider instrument identifier in snapshot",
                )
            )
            continue
        seen_providers.add(pid)

        if pid is not None and pid in explicit:
            hid = explicit[pid]
            if hid in hermes_ids:
                rows.append(
                    InstrumentReconciliationRow(
                        provider_instrument_id=pid,
                        isin=pos.isin,
                        ticker=pos.ticker,
                        display_name=pos.display_name,
                        hermes_instrument_id=hid,
                        status=InstrumentMatchStatus.MATCHED,
                        reason="explicit owner mapping",
                    )
                )
            else:
                rows.append(
                    InstrumentReconciliationRow(
                        provider_instrument_id=pid,
                        isin=pos.isin,
                        ticker=pos.ticker,
                        display_name=pos.display_name,
                        hermes_instrument_id=hid,
                        status=InstrumentMatchStatus.CONFLICT,
                        reason="explicit mapping targets a Hermes instrument id that does not exist",
                    )
                )
            continue

        # Allowed deterministic rule: exact normalized ISIN match when exactly
        # one Hermes instrument matches and the provider row has an ISIN.
        if pos.isin:
            matches = isin_index.get(pos.isin, [])
            if len(matches) == 1:
                rows.append(
                    InstrumentReconciliationRow(
                        provider_instrument_id=pid,
                        isin=pos.isin,
                        ticker=pos.ticker,
                        display_name=pos.display_name,
                        hermes_instrument_id=matches[0].instrument_id,
                        status=InstrumentMatchStatus.MATCHED,
                        reason="exact unique ISIN match",
                    )
                )
            elif len(matches) > 1:
                rows.append(
                    InstrumentReconciliationRow(
                        provider_instrument_id=pid,
                        isin=pos.isin,
                        ticker=pos.ticker,
                        display_name=pos.display_name,
                        hermes_instrument_id=None,
                        status=InstrumentMatchStatus.AMBIGUOUS,
                        reason="multiple Hermes instruments share this ISIN",
                    )
                )
            else:
                rows.append(
                    InstrumentReconciliationRow(
                        provider_instrument_id=pid,
                        isin=pos.isin,
                        ticker=pos.ticker,
                        display_name=pos.display_name,
                        hermes_instrument_id=None,
                        status=InstrumentMatchStatus.UNMATCHED,
                        reason="no Hermes instrument with this ISIN",
                    )
                )
        else:
            # No ISIN and no explicit mapping: ticker/name are hints only and
            # MUST NOT auto-match. Provider id alone is provenance, not identity.
            rows.append(
                InstrumentReconciliationRow(
                    provider_instrument_id=pid,
                    isin=pos.isin,
                    ticker=pos.ticker,
                    display_name=pos.display_name,
                    hermes_instrument_id=None,
                    status=InstrumentMatchStatus.UNMATCHED,
                    reason="no ISIN and no explicit mapping; ticker/name/provider id are not identity",
                )
            )
    return tuple(rows)
