"""Top-level provider-neutral reconciliation preview (R06-04).

Read-only, deterministic, provider-neutral. Fail-closed on incomplete/non-eligible
snapshots and on unresolved account/instrument identity. No writes, no network,
no persistence, no apply surface.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from hermes_finance.broker_data.dto import SnapshotStatus
from hermes_finance.broker_data.reconciliation.cash import reconcile_cash
from hermes_finance.broker_data.reconciliation.dto import (
    HermesStateView,
    OwnerMappingInput,
    ReconciliationPreview,
    ReconciliationStatus,
)
from hermes_finance.broker_data.reconciliation.matching import (
    reconcile_accounts,
    reconcile_instruments,
)
from hermes_finance.broker_data.reconciliation.positions import reconcile_positions


def _non_applicable(
    *,
    snapshot: object,
    hermes: HermesStateView,
    reason: str,
) -> ReconciliationPreview:
    return ReconciliationPreview(
        status=ReconciliationStatus.NON_APPLICABLE,
        provider=getattr(snapshot, "provider", "unknown"),
        source_as_of=getattr(snapshot, "source_as_of", None),
        captured_at=datetime.now(timezone.utc),
        eligible_for_apply=False,
        snapshot_status=getattr(snapshot, "status", SnapshotStatus.MALFORMED_RESPONSE),
        month_id=hermes.month_id,
        month_status=hermes.month_status,
        month_closed=hermes.month_status == "closed",
        would_touch_closed_month=False,
        accounts=(),
        instruments=(),
        positions=(),
        cash=(),
        warnings=(reason,),
        conflict_count=0,
    )


def build_reconciliation_preview(
    *,
    snapshot: object,
    hermes: HermesStateView,
    mapping: OwnerMappingInput,
) -> ReconciliationPreview:
    if not isinstance(snapshot, object) or not hasattr(snapshot, "status"):
        raise TypeError("snapshot must be a BrokerSnapshot")

    # Fail-closed gate: only COMPLETE + eligible_for_apply snapshots are
    # apply-candidate. Anything else yields a diagnostic non-applicable preview.
    status = snapshot.status
    provenance = getattr(snapshot, "provenance", None)
    eligible = bool(getattr(provenance, "eligible_for_apply", False))
    if status is not SnapshotStatus.COMPLETE or not eligible:
        return _non_applicable(
            snapshot=snapshot,
            hermes=hermes,
            reason=(
                "snapshot is not an apply-candidate: "
                f"status={status.value if isinstance(status, SnapshotStatus) else status}, "
                f"eligible_for_apply={eligible}"
            ),
        )

    account_rows = reconcile_accounts(snapshot=snapshot, hermes=hermes, mapping=mapping)
    instrument_rows = reconcile_instruments(snapshot=snapshot, hermes=hermes, mapping=mapping)
    position_rows = reconcile_positions(
        snapshot=snapshot,
        hermes=hermes,
        account_rows=account_rows,
        instrument_rows=instrument_rows,
    )
    cash_rows = reconcile_cash(snapshot=snapshot, hermes=hermes, account_rows=account_rows)

    conflict_counter = Counter()
    for row in account_rows:
        if row.status.value == "conflict":
            conflict_counter["account"] += 1
    for row in instrument_rows:
        if row.status.value in {"conflict", "ambiguous"}:
            conflict_counter["instrument"] += 1
    for row in position_rows:
        if row.status.value == "conflict":
            conflict_counter["position"] += 1

    conflict_count = sum(conflict_counter.values())

    if conflict_count > 0:
        status_value = ReconciliationStatus.CONFLICTS
    else:
        has_any_match = any(r.status.value == "matched" for r in account_rows) or any(
            r.status.value == "matched" for r in instrument_rows
        )
        status_value = (
            ReconciliationStatus.APPLICABLE
            if has_any_match
            else ReconciliationStatus.NON_APPLICABLE
        )

    # B2: apply eligibility of the preview is independent from the source
    # snapshot. A reconciliation preview is eligible for a future selective apply
    # ONLY when it is APPLICABLE. NON_APPLICABLE and CONFLICTS must never expose
    # eligible_for_apply=True (fail-closed).
    preview_eligible = status_value is ReconciliationStatus.APPLICABLE

    month_closed = hermes.month_status == "closed"
    would_touch_closed_month = month_closed and status_value in {
        ReconciliationStatus.APPLICABLE,
        ReconciliationStatus.CONFLICTS,
    }

    return ReconciliationPreview(
        status=status_value,
        provider=snapshot.provider,
        source_as_of=snapshot.source_as_of,
        captured_at=datetime.now(timezone.utc),
        eligible_for_apply=preview_eligible,
        snapshot_status=status,
        month_id=hermes.month_id,
        month_status=hermes.month_status,
        month_closed=month_closed,
        would_touch_closed_month=would_touch_closed_month,
        accounts=account_rows,
        instruments=instrument_rows,
        positions=position_rows,
        cash=cash_rows,
        warnings=(),
        conflict_count=conflict_count,
    )
