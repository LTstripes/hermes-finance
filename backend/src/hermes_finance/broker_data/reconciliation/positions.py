"""Pure position reconciliation between a BrokerSnapshot and Hermes state.

Only explicit account+instrument identity resolution produces a comparable
row. Quantities are compared exactly (Decimal). Provider price/NKD/unrealized
and Hermes kopeck values are preserved as provenance but marked non-comparable
because no accepted cross-semantic exists (different units/currency/scale).
No Hermes row is created or deleted; no market value is synthesized.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from hermes_finance.broker_data.dto import BrokerPosition, BrokerSnapshot
from hermes_finance.broker_data.reconciliation.dto import (
    AccountReconciliationRow,
    HermesStateView,
    InstrumentReconciliationRow,
    PositionReconciliationRow,
    PositionRowStatus,
    ValueComparability,
)


def _account_resolution(
    account_rows: tuple[AccountReconciliationRow, ...],
) -> dict[str, int | None]:
    """provider_account_id -> hermes_account_id for matched accounts only.

    A duplicate-provider-id CONFLICT row must not erase the resolved identity
    of the first matched account row for that provider id.
    """
    resolved: dict[str, int | None] = {}
    for row in account_rows:
        if row.status.value == "matched":
            if row.provider_account_id not in resolved:
                resolved[row.provider_account_id] = row.hermes_account_id
    return resolved


def _instrument_resolution(
    instrument_rows: tuple[InstrumentReconciliationRow, ...],
) -> dict[str | None, int | None]:
    """provider_instrument_id -> hermes_instrument_id for matched instruments."""
    resolved: dict[str | None, int | None] = {}
    for row in instrument_rows:
        if row.status.value == "matched":
            if row.provider_instrument_id not in resolved:
                resolved[row.provider_instrument_id] = row.hermes_instrument_id
    return resolved


def _hermes_position_index(
    hermes: HermesStateView,
) -> dict[tuple[int, int], object]:
    index: dict[tuple[int, int], object] = {}
    for pos in hermes.positions:
        index[(pos.account_id, pos.instrument_id)] = pos
    return index


def reconcile_positions(
    *,
    snapshot: BrokerSnapshot,
    hermes: HermesStateView,
    account_rows: tuple[AccountReconciliationRow, ...],
    instrument_rows: tuple[InstrumentReconciliationRow, ...],
) -> tuple[PositionReconciliationRow, ...]:
    account_res = _account_resolution(account_rows)
    instrument_res = _instrument_resolution(instrument_rows)
    hermes_index = _hermes_position_index(hermes)

    # Group provider positions by resolved (account_id, instrument_id).
    grouped: dict[tuple[int, int], list[BrokerPosition]] = defaultdict(list)
    raw_provider_pairs: list[tuple[int, int, BrokerPosition]] = []
    for pos in snapshot.positions:
        hid = instrument_res.get(pos.provider_instrument_id)
        aid = account_res.get(pos.provider_account_id)
        if hid is None or aid is None:
            # Unresolved identity: reflected by account/instrument rows, not a
            # position row. Provider-only positions require resolved identity.
            continue
        key = (aid, hid)
        grouped[key].append(pos)
        raw_provider_pairs.append((aid, hid, pos))

    resolved_pairs = set(grouped.keys())
    rows: list[PositionReconciliationRow] = []

    # Duplicate provider rows mapping to one canonical account+instrument fail
    # closed as conflict (no documented authoritative aggregation rule exists).
    for key, positions in grouped.items():
        account_id, instrument_id = key
        if len(positions) > 1:
            rows.append(
                PositionReconciliationRow(
                    account_id=account_id,
                    instrument_id=instrument_id,
                    status=PositionRowStatus.CONFLICT,
                    hermes_quantity=None,
                    provider_quantity=None,
                    quantity_difference=None,
                    quantity_equal=None,
                    hermes_market_price_per_unit_kopecks=None,
                    provider_broker_unit_price=None,
                    price_comparable=ValueComparability.NON_COMPARABLE,
                    hermes_accrued_interest_kopecks=None,
                    provider_accrued_interest_nkd=None,
                    nkd_comparable=ValueComparability.NON_COMPARABLE,
                    hermes_unrealized_result_kopecks=None,
                    provider_unrealized_result=None,
                    unrealized_comparable=ValueComparability.NON_COMPARABLE,
                    reason="duplicate provider rows map to the same canonical account+instrument; no aggregation rule",
                    warnings=(),
                )
            )
            continue

        provider_pos = positions[0]
        hermes_pos = hermes_index.get(key)
        if hermes_pos is None:
            rows.append(
                PositionReconciliationRow(
                    account_id=account_id,
                    instrument_id=instrument_id,
                    status=PositionRowStatus.PROVIDER_ONLY,
                    hermes_quantity=None,
                    provider_quantity=provider_pos.quantity,
                    quantity_difference=None,
                    quantity_equal=None,
                    hermes_market_price_per_unit_kopecks=None,
                    provider_broker_unit_price=provider_pos.broker_unit_price,
                    price_comparable=ValueComparability.NON_COMPARABLE,
                    hermes_accrued_interest_kopecks=None,
                    provider_accrued_interest_nkd=provider_pos.accrued_interest_nkd,
                    nkd_comparable=ValueComparability.NON_COMPARABLE,
                    hermes_unrealized_result_kopecks=None,
                    provider_unrealized_result=provider_pos.unrealized_result,
                    unrealized_comparable=ValueComparability.NON_COMPARABLE,
                    reason="provider-only position; no matching Hermes position",
                    warnings=(),
                )
            )
            continue

        hermes_qty: Decimal = hermes_pos.quantity
        provider_qty = provider_pos.quantity
        warnings: list[str] = []
        if provider_qty is None:
            warnings.append("provider quantity unavailable; cannot compare")
        quantity_equal: bool | None = None
        quantity_difference: Decimal | None = None
        if provider_qty is not None:
            quantity_equal = hermes_qty == provider_qty
            quantity_difference = hermes_qty - provider_qty

        rows.append(
            PositionReconciliationRow(
                account_id=account_id,
                instrument_id=instrument_id,
                status=PositionRowStatus.MATCHED,
                hermes_quantity=hermes_qty,
                provider_quantity=provider_qty,
                quantity_difference=quantity_difference,
                quantity_equal=quantity_equal,
                hermes_market_price_per_unit_kopecks=hermes_pos.market_price_per_unit_kopecks,
                provider_broker_unit_price=provider_pos.broker_unit_price,
                price_comparable=ValueComparability.NON_COMPARABLE,
                hermes_accrued_interest_kopecks=hermes_pos.accrued_interest_kopecks,
                provider_accrued_interest_nkd=provider_pos.accrued_interest_nkd,
                nkd_comparable=ValueComparability.NON_COMPARABLE,
                hermes_unrealized_result_kopecks=hermes_pos.unrealized_result_kopecks,
                provider_unrealized_result=provider_pos.unrealized_result,
                unrealized_comparable=ValueComparability.NON_COMPARABLE,
                reason=None,
                warnings=tuple(warnings),
            )
        )

    # Hermes-only positions: present in Hermes, absent from resolved provider.
    for pos in hermes.positions:
        key = (pos.account_id, pos.instrument_id)
        if key in resolved_pairs:
            continue
        rows.append(
            PositionReconciliationRow(
                account_id=pos.account_id,
                instrument_id=pos.instrument_id,
                status=PositionRowStatus.HERMES_ONLY,
                hermes_quantity=pos.quantity,
                provider_quantity=None,
                quantity_difference=None,
                quantity_equal=None,
                hermes_market_price_per_unit_kopecks=pos.market_price_per_unit_kopecks,
                provider_broker_unit_price=None,
                price_comparable=ValueComparability.NON_COMPARABLE,
                hermes_accrued_interest_kopecks=pos.accrued_interest_kopecks,
                provider_accrued_interest_nkd=None,
                nkd_comparable=ValueComparability.NON_COMPARABLE,
                hermes_unrealized_result_kopecks=pos.unrealized_result_kopecks,
                provider_unrealized_result=None,
                unrealized_comparable=ValueComparability.NON_COMPARABLE,
                reason="Hermes-only position; no provider row with resolved identity",
                warnings=(),
            )
        )

    return tuple(rows)
