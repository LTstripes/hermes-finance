"""Normalized, provider-neutral reconciliation rows (R07-08A).

This module adapts the accepted R06-04 reconciliation preview into the small
row-state vocabulary needed by the future Reconciliation Center. It does not
load persistence, call a provider, write a database, or infer identity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState
from hermes_finance.broker_data.dto import BrokerPosition, BrokerSnapshot, SnapshotStatus
from hermes_finance.broker_data.reconciliation.dto import (
    AccountMatchStatus,
    AccountReconciliationRow,
    HermesAccountView,
    HermesInstrumentView,
    HermesStateView,
    InstrumentMatchStatus,
    InstrumentReconciliationRow,
    NormalizedReconciliationResult,
    NormalizedReconciliationRow,
    NormalizedRowState,
    OwnerMappingInput,
    PositionReconciliationRow,
    PositionRowStatus,
    ReconciliationPreview,
    ReconciliationStatus,
    ValueComparability,
)
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview


def build_normalized_reconciliation(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
) -> NormalizedReconciliationResult:
    """Build a normalized read-only result from one explicit snapshot.

    The existing preview remains the source of truth for eligibility, mapping
    and conflict behavior. Resolved position rows are translated as follows:
    equal quantity -> ``matched``, unequal quantity -> ``differs``, provider
    only -> ``missing_local`` and Hermes only -> ``missing_provider``. A
    provider row whose identity cannot be resolved is retained as
    ``unresolved`` so it is not silently mistaken for a missing row.
    """

    if not isinstance(snapshot, BrokerSnapshot):
        raise TypeError("snapshot must be a BrokerSnapshot")

    preview = build_reconciliation_preview(snapshot=snapshot, hermes=hermes, mapping=mapping)
    provenance = snapshot.provenance
    compatibility_state = getattr(provenance, "compatibility_state", AlfaCompatibilityState.UNKNOWN)
    if not isinstance(compatibility_state, AlfaCompatibilityState):
        compatibility_state = AlfaCompatibilityState.UNKNOWN
    compatibility_fingerprint = getattr(provenance, "compatibility_fingerprint", None)

    if _snapshot_is_stale(snapshot):
        return _result_from_preview(
            preview=preview,
            hermes=hermes,
            compatibility_state=compatibility_state,
            compatibility_fingerprint=compatibility_fingerprint,
            rows=(),
            warnings=(
                *preview.warnings,
                "snapshot is stale; an explicit owner-triggered refresh is required",
            ),
            stale=True,
        )

    source_is_usable = (
        snapshot.status is SnapshotStatus.COMPLETE
        and bool(provenance.eligible_for_apply)
        and compatibility_state is AlfaCompatibilityState.COMPATIBLE
    )
    if not source_is_usable:
        compatibility_warning = ()
        if compatibility_state is not AlfaCompatibilityState.COMPATIBLE:
            compatibility_warning = (
                f"snapshot compatibility is not confirmed: state={compatibility_state.value}",
            )
        return _result_from_preview(
            preview=preview,
            hermes=hermes,
            compatibility_state=compatibility_state,
            compatibility_fingerprint=compatibility_fingerprint,
            rows=(),
            warnings=(*preview.warnings, *compatibility_warning),
            status=(
                ReconciliationStatus.NON_APPLICABLE
                if compatibility_state is not AlfaCompatibilityState.COMPATIBLE
                else None
            ),
        )

    account_rows = preview.accounts
    instrument_rows = preview.instruments
    position_rows = preview.positions
    account_by_provider_id = _first_account_rows(account_rows)
    instrument_by_provider_id = _first_instrument_rows(instrument_rows)
    hermes_accounts = {account.account_id: account for account in hermes.accounts}
    hermes_instruments = {instrument.instrument_id: instrument for instrument in hermes.instruments}

    provider_by_identity: dict[tuple[int, int], list[BrokerPosition]] = defaultdict(list)
    unresolved_provider_positions: list[tuple[BrokerPosition, str, int | None, int | None]] = []
    for provider_position in snapshot.positions:
        account_row = account_by_provider_id.get(provider_position.provider_account_id)
        instrument_row = instrument_by_provider_id.get(provider_position.provider_instrument_id)
        account_id = _matched_account_id(account_row)
        instrument_id = _matched_instrument_id(instrument_row)
        if account_id is None or instrument_id is None:
            unresolved_provider_positions.append(
                (
                    provider_position,
                    _unresolved_reason(account_row, instrument_row),
                    account_id,
                    instrument_id,
                )
            )
            continue
        provider_by_identity[(account_id, instrument_id)].append(provider_position)

    rows: list[NormalizedReconciliationRow] = []
    for position_row in position_rows:
        key = (position_row.account_id, position_row.instrument_id)
        provider_positions = provider_by_identity.get(key, [])
        provider_position = provider_positions[0] if len(provider_positions) == 1 else None
        normalized_row = _normalized_position_row(
            position_row=position_row,
            provider_position=provider_position,
            hermes_account=hermes_accounts.get(position_row.account_id),
            hermes_instrument=hermes_instruments.get(position_row.instrument_id),
        )
        if position_row.status is PositionRowStatus.HERMES_ONLY and not _can_prove_missing_provider(
            position_row=position_row,
            account_rows=account_rows,
            mapping=mapping,
            hermes_instruments=hermes_instruments,
        ):
            normalized_row = replace(
                normalized_row,
                state=NormalizedRowState.UNRESOLVED,
                reason=(
                    "provider absence cannot be established until the local "
                    "account and instrument mappings are explicitly resolved"
                ),
            )
        rows.append(normalized_row)

    for provider_position, reason, account_id, instrument_id in unresolved_provider_positions:
        instrument_row = instrument_by_provider_id.get(provider_position.provider_instrument_id)
        rows.append(
            _unresolved_provider_row(
                provider_position=provider_position,
                reason=reason,
                account_id=account_id,
                instrument_id=instrument_id,
                hermes_accounts=hermes_accounts,
                hermes_instruments=hermes_instruments,
                instrument_row=instrument_row,
            )
        )

    return _result_from_preview(
        preview=preview,
        hermes=hermes,
        compatibility_state=compatibility_state,
        compatibility_fingerprint=compatibility_fingerprint,
        rows=tuple(rows),
        warnings=preview.warnings,
    )


def _result_from_preview(
    *,
    preview: ReconciliationPreview,
    hermes: HermesStateView,
    compatibility_state: AlfaCompatibilityState,
    compatibility_fingerprint: str | None,
    rows: tuple[NormalizedReconciliationRow, ...],
    warnings: tuple[str, ...],
    stale: bool = False,
    status: ReconciliationStatus | None = None,
) -> NormalizedReconciliationResult:
    return NormalizedReconciliationResult(
        status=status or preview.status,
        provider=preview.provider,
        source_as_of=preview.source_as_of,
        captured_at=preview.captured_at,
        snapshot_status=preview.snapshot_status,
        compatibility_state=compatibility_state,
        compatibility_fingerprint=compatibility_fingerprint,
        month_id=hermes.month_id,
        month_status=hermes.month_status,
        month_closed=preview.month_closed,
        rows=rows,
        accounts=preview.accounts,
        instruments=preview.instruments,
        cash=preview.cash,
        warnings=tuple(dict.fromkeys(warnings)),
        snapshot_fingerprint=None,
        stale=stale,
    )


def _snapshot_is_stale(snapshot: BrokerSnapshot) -> bool:
    diagnostics = getattr(snapshot, "diagnostics", None)
    return bool(
        snapshot.status is SnapshotStatus.STALE
        or getattr(diagnostics, "snapshot_status", None) == SnapshotStatus.STALE.value
    )


def _first_account_rows(
    rows: tuple[AccountReconciliationRow, ...],
) -> dict[str, AccountReconciliationRow]:
    result: dict[str, AccountReconciliationRow] = {}
    for row in rows:
        result.setdefault(row.provider_account_id, row)
    return result


def _first_instrument_rows(
    rows: tuple[InstrumentReconciliationRow, ...],
) -> dict[str | None, InstrumentReconciliationRow]:
    result: dict[str | None, InstrumentReconciliationRow] = {}
    for row in rows:
        result.setdefault(row.provider_instrument_id, row)
    return result


def _matched_account_id(row: AccountReconciliationRow | None) -> int | None:
    if row is None or row.status is not AccountMatchStatus.MATCHED:
        return None
    return row.hermes_account_id


def _matched_instrument_id(row: InstrumentReconciliationRow | None) -> int | None:
    if row is None or row.status is not InstrumentMatchStatus.MATCHED:
        return None
    return row.hermes_instrument_id


def _unresolved_reason(
    account_row: AccountReconciliationRow | None,
    instrument_row: InstrumentReconciliationRow | None,
) -> str:
    reasons: list[str] = []
    if account_row is None:
        reasons.append("provider account is not present in the snapshot account set")
    elif account_row.status is not AccountMatchStatus.MATCHED:
        reasons.append(account_row.reason or "provider account mapping is unresolved")
    if instrument_row is None:
        reasons.append("provider instrument is not present in the snapshot identity set")
    elif instrument_row.status is not InstrumentMatchStatus.MATCHED:
        reasons.append(instrument_row.reason or "provider instrument mapping is unresolved")
    return "; ".join(reasons)


def _normalized_position_row(
    *,
    position_row: PositionReconciliationRow,
    provider_position: BrokerPosition | None,
    hermes_account: HermesAccountView | None,
    hermes_instrument: HermesInstrumentView | None,
) -> NormalizedReconciliationRow:
    state = _normalized_state(position_row)
    reason = position_row.reason
    if state is NormalizedRowState.DIFFERS:
        reason = "quantity differs"
    if state is NormalizedRowState.UNRESOLVED and reason is None:
        reason = "position identity or provider quantity is unresolved"

    return NormalizedReconciliationRow(
        state=state,
        account_id=position_row.account_id,
        instrument_id=position_row.instrument_id,
        account_name=hermes_account.name if hermes_account is not None else None,
        instrument_name=hermes_instrument.name if hermes_instrument is not None else None,
        instrument_isin=hermes_instrument.isin if hermes_instrument is not None else None,
        instrument_ticker=hermes_instrument.ticker if hermes_instrument is not None else None,
        provider_account_id=(
            provider_position.provider_account_id if provider_position is not None else None
        ),
        provider_instrument_id=(
            provider_position.provider_instrument_id if provider_position is not None else None
        ),
        hermes_quantity=position_row.hermes_quantity,
        provider_quantity=position_row.provider_quantity,
        quantity_difference=position_row.quantity_difference,
        quantity_equal=position_row.quantity_equal,
        hermes_market_price_per_unit_kopecks=position_row.hermes_market_price_per_unit_kopecks,
        provider_broker_unit_price=position_row.provider_broker_unit_price,
        provider_accounting_price=(
            provider_position.accounting_price if provider_position is not None else None
        ),
        provider_market_value=(
            provider_position.market_value if provider_position is not None else None
        ),
        price_comparable=position_row.price_comparable,
        hermes_accrued_interest_kopecks=position_row.hermes_accrued_interest_kopecks,
        provider_accrued_interest_nkd=position_row.provider_accrued_interest_nkd,
        nkd_comparable=position_row.nkd_comparable,
        hermes_unrealized_result_kopecks=position_row.hermes_unrealized_result_kopecks,
        provider_unrealized_result=position_row.provider_unrealized_result,
        unrealized_comparable=position_row.unrealized_comparable,
        reason=reason,
        warnings=position_row.warnings,
    )


def _unresolved_provider_row(
    *,
    provider_position: BrokerPosition,
    reason: str,
    account_id: int | None,
    instrument_id: int | None,
    hermes_accounts: dict[int, HermesAccountView],
    hermes_instruments: dict[int, HermesInstrumentView],
    instrument_row: InstrumentReconciliationRow | None,
) -> NormalizedReconciliationRow:
    instrument = hermes_instruments.get(instrument_id) if instrument_id is not None else None
    return NormalizedReconciliationRow(
        state=NormalizedRowState.UNRESOLVED,
        account_id=account_id,
        instrument_id=instrument_id,
        account_name=(
            hermes_accounts[account_id].name
            if account_id is not None and account_id in hermes_accounts
            else None
        ),
        instrument_name=instrument.name if instrument is not None else None,
        instrument_isin=(
            instrument.isin
            if instrument is not None
            else instrument_row.isin
            if instrument_row is not None
            else None
        ),
        instrument_ticker=(
            instrument.ticker
            if instrument is not None
            else instrument_row.ticker
            if instrument_row is not None
            else None
        ),
        provider_account_id=provider_position.provider_account_id,
        provider_instrument_id=provider_position.provider_instrument_id,
        hermes_quantity=None,
        provider_quantity=provider_position.quantity,
        quantity_difference=None,
        quantity_equal=None,
        hermes_market_price_per_unit_kopecks=None,
        provider_broker_unit_price=provider_position.broker_unit_price,
        provider_accounting_price=provider_position.accounting_price,
        provider_market_value=provider_position.market_value,
        price_comparable=ValueComparability.NON_COMPARABLE,
        hermes_accrued_interest_kopecks=None,
        provider_accrued_interest_nkd=provider_position.accrued_interest_nkd,
        nkd_comparable=ValueComparability.NON_COMPARABLE,
        hermes_unrealized_result_kopecks=None,
        provider_unrealized_result=provider_position.unrealized_result,
        unrealized_comparable=ValueComparability.NON_COMPARABLE,
        reason=reason,
        warnings=(),
    )


def _normalized_state(position_row: PositionReconciliationRow) -> NormalizedRowState:
    if position_row.status is PositionRowStatus.PROVIDER_ONLY:
        return NormalizedRowState.MISSING_LOCAL
    if position_row.status is PositionRowStatus.HERMES_ONLY:
        return NormalizedRowState.MISSING_PROVIDER
    if position_row.status is PositionRowStatus.CONFLICT:
        return NormalizedRowState.UNRESOLVED
    if position_row.quantity_equal is True:
        return NormalizedRowState.MATCHED
    if position_row.quantity_equal is False:
        return NormalizedRowState.DIFFERS
    return NormalizedRowState.UNRESOLVED


def _can_prove_missing_provider(
    *,
    position_row: PositionReconciliationRow,
    account_rows: tuple[AccountReconciliationRow, ...],
    mapping: OwnerMappingInput,
    hermes_instruments: dict[int, HermesInstrumentView],
) -> bool:
    """Require both canonical sides before calling a row provider-missing."""

    account_resolved = any(
        row.status is AccountMatchStatus.MATCHED
        and row.hermes_account_id == position_row.account_id
        for row in account_rows
    )
    instrument_provider_ids = {
        item.provider_instrument_id
        for item in mapping.instruments
        if item.hermes_instrument_id == position_row.instrument_id
    }
    return (
        account_resolved
        and position_row.instrument_id in hermes_instruments
        and len(instrument_provider_ids) == 1
    )
