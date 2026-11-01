# Hermes Finance 1.9.2

Saved broker statements can receive reviewed bookkeeping and trade confirmations
without importing their positions, cash or paid income again. Exact native bond
evidence supports both purchases and sales, complete NKD occurrence groups and
account-level commissions. A separately confirmed broker bonus can be recorded as
source-bound evidence without a second cash credit, payout or Owner contribution.
Unresolved evidence continues to block the affected account.

The release adds backend proof operations; the general statement interface remains
unchanged. Existing financial SOURCE and Money v1/v2 records remain readable.
New proofs require this compatible backend before they are saved. Schema0068,
stored financial amounts and CLOSED history are not rewritten.

Source-only investment confirmations remain bound to their exact Python
implementation. The frozen metadata-only 1.9.1 compatibility exception does not
certify these financial changes: older confirmations require fresh review before
their derived figures are current. Their evidence is preserved, never silently
reissued or accepted under a new implementation.

Use the existing backup-first [O3 workflow](OWNER_RUNTIME_OPERATIONS.md#o3) with the
exact published release. Publication, installation, financial confirmation and
Close remain separate actions. Installed identities belong to
[CURRENT_STATUS](CURRENT_STATUS.md).
