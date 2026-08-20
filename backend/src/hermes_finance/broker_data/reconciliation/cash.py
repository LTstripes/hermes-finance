"""Cash reconciliation between a BrokerSnapshot and Hermes state (R06-04).

Hermes ``cash_balances`` are month-scoped and carry no account identity, so an
account+currency comparable cash diff is structurally unavailable on the
current schema. Per issue #83, missing comparability must be surfaced as
``non_comparable``, never synthesized or FX-converted. This module records the
provider cash observations with provenance and marks them non-comparable; it
does NOT invent a Hermes-side counterpart or perform cross-currency math.
"""

from __future__ import annotations

from hermes_finance.broker_data.dto import BrokerSnapshot
from hermes_finance.broker_data.reconciliation.dto import (
    AccountReconciliationRow,
    CashReconciliationRow,
    CashRowStatus,
    HermesStateView,
)


def reconcile_cash(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    account_rows: tuple[AccountReconciliationRow, ...],
) -> tuple[CashReconciliationRow, ...]:
    # Only record provider cash that maps to an explicitly matched account.
    matched_accounts = {
        row.provider_account_id for row in account_rows if row.status.value == "matched"
    }
    rows: list[CashReconciliationRow] = []
    for balance in snapshot.cash_balances:
        pid = balance.provider_account_id
        if pid is None or pid not in matched_accounts:
            continue
        hermes_account_id = None
        for row in account_rows:
            if row.provider_account_id == pid and row.status.value == "matched":
                hermes_account_id = row.hermes_account_id
                break
        rows.append(
            CashReconciliationRow(
                provider_account_id=pid,
                hermes_account_id=hermes_account_id,
                currency=balance.currency,
                provider_amount=balance.amount,
                status=CashRowStatus.NON_COMPARABLE,
                reason=(
                    "Hermes cash balances are month-scoped without account identity; "
                    "no account+currency comparable counterpart exists"
                ),
            )
        )
    return tuple(rows)
