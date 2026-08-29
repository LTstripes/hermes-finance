"""Provider-neutral reconciliation/preview package (R06-04).

Pure domain + read-only adapter only. Importing this package does not open a
network, write to the database, persist, apply or expose an API/UI surface.
"""

from __future__ import annotations

from hermes_finance.broker_data.reconciliation.cash import reconcile_cash
from hermes_finance.broker_data.reconciliation.dto import (
    COMPARISON_ONLY_PROVIDER_FIELDS,
    AccountMappingInput,
    AccountMatchStatus,
    AccountObservedInstrument,
    AccountReconciliationRow,
    CashReconciliationRow,
    CashRowStatus,
    HermesAccountView,
    HermesCashView,
    HermesInstrumentView,
    HermesPositionView,
    HermesStateView,
    InstrumentMappingInput,
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
from hermes_finance.broker_data.reconciliation.matching import (
    reconcile_accounts,
    reconcile_instruments,
)
from hermes_finance.broker_data.reconciliation.normalized import build_normalized_reconciliation
from hermes_finance.broker_data.reconciliation.positions import reconcile_positions
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview
from hermes_finance.services.broker_reconciliation import load_hermes_state_for_month

__all__ = [
    "AccountMappingInput",
    "AccountMatchStatus",
    "AccountObservedInstrument",
    "AccountReconciliationRow",
    "CashReconciliationRow",
    "CashRowStatus",
    "COMPARISON_ONLY_PROVIDER_FIELDS",
    "HermesAccountView",
    "HermesCashView",
    "HermesInstrumentView",
    "HermesPositionView",
    "HermesStateView",
    "InstrumentMappingInput",
    "InstrumentMatchStatus",
    "InstrumentReconciliationRow",
    "NormalizedReconciliationResult",
    "NormalizedReconciliationRow",
    "NormalizedRowState",
    "OwnerMappingInput",
    "PositionReconciliationRow",
    "PositionRowStatus",
    "ReconciliationPreview",
    "ReconciliationStatus",
    "ValueComparability",
    "build_reconciliation_preview",
    "build_normalized_reconciliation",
    "load_hermes_state_for_month",
    "reconcile_accounts",
    "reconcile_cash",
    "reconcile_instruments",
    "reconcile_positions",
]
