"""Read-only adapter: build a HermesStateView from a reporting month (R06-04).

This lives in the service layer (not in ``broker_data``) because the R06-03
source guard forbids the ``broker_data`` package from importing SQLAlchemy
persistence. The reconciliation domain package stays pure; this module is the
narrow read-only boundary that loads relevant Hermes investment/account state.

Performs ZERO writes; the session is left untouched. Broker snapshot provider
data is NOT persisted here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState
from hermes_finance.broker_data.dto import BrokerSnapshot, SnapshotStatus
from hermes_finance.broker_data.protocol import BrokerSnapshotProvider
from hermes_finance.broker_data.reconciliation.dto import (
    HermesAccountView,
    HermesCashView,
    HermesInstrumentView,
    HermesPositionView,
    HermesStateView,
    NormalizedReconciliationResult,
    NormalizedReconciliationRow,
    NormalizedRowState,
    OwnerMappingInput,
    PositionRowStatus,
    ReconciliationStatus,
)
from hermes_finance.broker_data.reconciliation.normalized import (
    build_normalized_reconciliation,
)
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview
from hermes_finance.persistence import (
    Account,
    CashBalance,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services.reporting_months import get_reporting_month


def load_hermes_state_for_month(session: Session, reporting_month_id: int) -> HermesStateView:
    month = get_reporting_month(session, reporting_month_id)
    month_status = str(month.status)

    accounts = list(session.scalars(select(Account).order_by(Account.id)))
    account_ids = {acc.id for acc in accounts}
    account_views = tuple(
        HermesAccountView(
            account_id=acc.id,
            name=acc.name,
            account_type=str(acc.account_type),
            external_code=acc.external_code,
            status=str(acc.status),
        )
        for acc in accounts
    )

    instruments = list(session.scalars(select(Instrument).order_by(Instrument.id)))
    instrument_ids = {inst.id for inst in instruments}
    instrument_views = tuple(
        HermesInstrumentView(
            instrument_id=inst.id,
            name=inst.name,
            instrument_type=str(inst.instrument_type),
            isin=inst.isin,
            ticker=inst.ticker,
        )
        for inst in instruments
    )

    positions = list(
        session.scalars(
            select(PositionSnapshot)
            .where(PositionSnapshot.reporting_month_id == reporting_month_id)
            .order_by(PositionSnapshot.account_id, PositionSnapshot.instrument_id)
        )
    )
    position_views: list[HermesPositionView] = []
    for pos in positions:
        if pos.account_id not in account_ids or pos.instrument_id not in instrument_ids:
            # Skip dangling references defensively; reconciliation needs both
            # sides canonical and present.
            continue
        position_views.append(
            HermesPositionView(
                account_id=pos.account_id,
                instrument_id=pos.instrument_id,
                quantity=Decimal(pos.quantity),
                market_price_per_unit_kopecks=pos.market_price_per_unit_kopecks,
                accrued_interest_kopecks=pos.accrued_interest_kopecks,
                market_value_kopecks=pos.market_value_kopecks,
                unrealized_result_kopecks=pos.unrealized_result_kopecks,
            )
        )

    cash = list(
        session.scalars(
            select(CashBalance).where(CashBalance.reporting_month_id == reporting_month_id)
        )
    )
    cash_views = tuple(
        HermesCashView(
            name=cb.name,
            amount_kopecks=cb.amount_kopecks,
            currency=str(cb.currency),
        )
        for cb in cash
    )

    return HermesStateView(
        month_id=month.id,
        month_status=month_status,
        accounts=account_views,
        instruments=instrument_views,
        positions=tuple(position_views),
        cash_balances=cash_views,
    )


def reconcile_broker_snapshot_read_only(
    session: Session,
    *,
    provider: BrokerSnapshotProvider,
    reporting_month_id: int,
    mapping: OwnerMappingInput,
    expected_row_fingerprints: Mapping[tuple[int, int], str] | None = None,
    expected_snapshot_fingerprint: str | None = None,
) -> NormalizedReconciliationResult:
    """Fetch one explicit provider snapshot and return a read-only result.

    The provider call belongs to this explicit service invocation. No cache,
    background refresh, transaction import, or session mutation is performed.
    """

    snapshot = provider.fetch_snapshot()
    if not isinstance(snapshot, BrokerSnapshot):
        raise TypeError("broker snapshot provider returned an invalid snapshot")
    hermes = load_hermes_state_for_month(session, reporting_month_id)
    return build_normalized_reconciliation_for_snapshot(
        session,
        snapshot=snapshot,
        hermes=hermes,
        mapping=mapping,
        expected_row_fingerprints=expected_row_fingerprints,
        expected_snapshot_fingerprint=expected_snapshot_fingerprint,
    )


def build_normalized_reconciliation_for_snapshot(
    session: Session,
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
    expected_row_fingerprints: Mapping[tuple[int, int], str] | None = None,
    expected_snapshot_fingerprint: str | None = None,
) -> NormalizedReconciliationResult:
    """Attach accepted per-position fingerprints without writing persistence."""

    result = build_normalized_reconciliation(snapshot=snapshot, hermes=hermes, mapping=mapping)
    if (
        result.stale
        or result.snapshot_status is not SnapshotStatus.COMPLETE
        or not snapshot.provenance.eligible_for_apply
        or result.compatibility_state is not AlfaCompatibilityState.COMPATIBLE
    ):
        return result

    # Import locally to preserve the existing broker_snapshot_apply -> this
    # module dependency while reusing its accepted fingerprint algorithm.
    from hermes_finance.services.broker_snapshot_apply import position_apply_fingerprint

    local_snapshots = {
        (position.account_id, position.instrument_id): position
        for position in session.scalars(
            select(PositionSnapshot).where(PositionSnapshot.reporting_month_id == result.month_id)
        )
    }
    preview = build_reconciliation_preview(snapshot=snapshot, hermes=hermes, mapping=mapping)
    legacy_rows = {
        (row.account_id, row.instrument_id): row
        for row in preview.positions
        if row.status in {PositionRowStatus.MATCHED, PositionRowStatus.PROVIDER_ONLY}
    }
    rows: list[NormalizedReconciliationRow] = []
    for row in result.rows:
        legacy_row = legacy_rows.get((row.account_id, row.instrument_id))
        if legacy_row is None:
            rows.append(row)
            continue
        fingerprint = position_apply_fingerprint(
            preview=preview,
            row=legacy_row,
            mapping=mapping,
            snapshot=local_snapshots.get((row.account_id, row.instrument_id)),
        )
        rows.append(replace(row, fingerprint=fingerprint))

    snapshot_fingerprint = _normalized_snapshot_fingerprint(
        result=replace(result, rows=tuple(rows)),
    )
    result = replace(
        result,
        rows=tuple(rows),
        snapshot_fingerprint=snapshot_fingerprint,
    )

    stale_keys = {
        key
        for key, expected in (expected_row_fingerprints or {}).items()
        if next(
            (row.fingerprint for row in result.rows if (row.account_id, row.instrument_id) == key),
            None,
        )
        != expected
    }
    if expected_snapshot_fingerprint is not None and (
        expected_snapshot_fingerprint != result.snapshot_fingerprint
    ):
        stale_keys.update(
            (row.account_id, row.instrument_id)
            for row in result.rows
            if row.account_id is not None and row.instrument_id is not None
        )
    if not stale_keys:
        return result

    stale_reason = "snapshot is stale; refresh the explicit broker snapshot before using it"
    stale_rows = tuple(
        replace(
            row,
            state=(
                NormalizedRowState.UNRESOLVED
                if (row.account_id, row.instrument_id) in stale_keys
                else row.state
            ),
            reason=(
                stale_reason if (row.account_id, row.instrument_id) in stale_keys else row.reason
            ),
            fingerprint=(
                None if (row.account_id, row.instrument_id) in stale_keys else row.fingerprint
            ),
            warnings=(
                *row.warnings,
                "stale fingerprint; no action is permitted",
            )
            if (row.account_id, row.instrument_id) in stale_keys
            else row.warnings,
        )
        for row in result.rows
    )
    return replace(
        result,
        status=ReconciliationStatus.NON_APPLICABLE,
        rows=stale_rows,
        warnings=(*result.warnings, stale_reason),
        stale=True,
    )


def _normalized_snapshot_fingerprint(*, result: NormalizedReconciliationResult) -> str:
    payload = {
        "schema": "hermes-reconciliation/v1",
        "provider": result.provider,
        "source_as_of": (
            _canonical_datetime(result.source_as_of) if result.source_as_of is not None else None
        ),
        "snapshot_status": result.snapshot_status.value,
        "compatibility_fingerprint": result.compatibility_fingerprint,
        "rows": [
            {
                "account_id": row.account_id,
                "instrument_id": row.instrument_id,
                "provider_account_id": row.provider_account_id,
                "provider_instrument_id": row.provider_instrument_id,
                "state": row.state.value,
                "fingerprint": row.fingerprint,
            }
            for row in result.rows
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_datetime(value: datetime) -> str:
    timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat()
