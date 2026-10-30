"""Read-only all-history presentation, without a cross-category return kernel.

Each source result keeps its exact original-bound interval and authority. Known
deposit receipts and saved gold valuation are separate components, never extra
operands added to investment P&L. The union model remains explicitly unavailable.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace

from sqlalchemy import select

from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    DepositSnapshot,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services import returns_view, source_investment_proofs
from hermes_finance.services.source_instrument_returns import _identities
from hermes_finance.services.source_monthly_returns import _selected_sources, source_read_snapshot
from hermes_finance.statement_import.mybroker import PROVIDER


def _unknown(reason, *, rate=False):
    return returns_view.metric(
        reasons=(reason,), unit="fraction" if rate else "kopecks", estimate=False
    )


def _period(month):
    return returns_view.bounds(month.period_start - timedelta(days=1), month.period_end)


def _deposits(session, months):
    rows = list(session.scalars(select(DepositSnapshot).order_by(DepositSnapshot.id)))
    by_month = defaultdict(list)
    for row in rows:
        by_month[row.reporting_month_id].append(row)
    periods, known, excluded = [], [], False
    for month in months:
        selected = by_month.get(month.id, [])
        if not selected and not rows:
            continue
        periods.append({"period": _period(month), "status": month.status, "rows": len(selected)})
        if month.status == "closed":
            known.extend(row.actual_interest_received_kopecks for row in selected)
        else:
            excluded = True
    reasons = ["known_received_interest_only", "deposit_full_history_not_proven"]
    if excluded:
        reasons.append("draft_deposit_interest_excluded")
    return {
        "interest": returns_view.metric(
            sum(known) if known else None,
            reasons=reasons,
            method="deposit_received_interest",
            estimate=False,
        ),
        "partial": True,
        "periods": periods,
        "reason_codes": reasons,
    }


def _gold(session, months):
    closed = {month.id: month for month in months if month.status == "closed"}
    rows = session.execute(
        select(PositionSnapshot, Instrument, Account)
        .join(Instrument, Instrument.id == PositionSnapshot.instrument_id)
        .join(Account, Account.id == PositionSnapshot.account_id)
        .where(Instrument.instrument_type == "gold")
        .order_by(PositionSnapshot.id)
    )
    latest = {}
    for position, instrument, account in rows:
        if position.reporting_month_id not in closed:
            continue
        month = closed[position.reporting_month_id]
        key = (account.id, instrument.id)
        rank = (month.period_end, position.id)
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, position, instrument, account, month)
    result = []
    for _, position, instrument, account, month in latest.values():
        reasons = ["saved_snapshot_unrealized_only", "current_catalogue_gold_classification"]
        if position.historical_instrument_type != "gold":
            reasons.append("historical_gold_classification_unproven")
        cost = position.cost_basis_kopecks
        value = position.market_value_kopecks
        unrealized = position.unrealized_result_kopecks
        consistent = cost is not None and unrealized is not None and value - cost == unrealized
        rate = None
        if not consistent:
            reasons.append("gold_snapshot_cost_result_missing_or_conflicting")
        elif cost > 0:
            with localcontext() as context:
                context.prec = 60
                rate = Decimal(unrealized) / Decimal(cost)
        else:
            reasons.append("gold_cost_return_denominator_unavailable")
        result.append(
            {
                "account_id": account.id,
                "instrument_id": instrument.id,
                "label": instrument.name,
                "date": position.price_date,
                "quantity": str(position.quantity),
                "market_value": returns_view.metric(value, reasons=reasons, estimate=False),
                "cost_basis": returns_view.metric(cost, reasons=reasons, estimate=False),
                "unrealized_result": returns_view.metric(
                    unrealized if consistent else None, reasons=reasons, estimate=False
                ),
                "cost_return": returns_view.metric(
                    rate,
                    reasons=reasons,
                    method="saved_unrealized_over_cost",
                    unit="fraction",
                    estimate=False,
                ),
            }
        )
    return {
        "snapshots": result,
        "period_result": _unknown("gold_dated_trade_history_unavailable"),
        "reason_codes": ["gold_period_return_unproven", "snapshot_result_not_period_return"],
    }


def _source_accounts(session):
    canonical = returns_view._source_scopes(session)
    labels = {a["id"]: a["label"] for a in returns_view._accounts(session, canonical)}
    accounts, grouped = [], defaultdict(list)
    for account in sorted(set(canonical.values())):
        scope = f"source:{account}"
        captured = {}
        reports = source_investment_proofs.read_report_summaries(
            session, source_account=account, analyses=captured
        )
        historical = [p for p in reports if p["history_from_zero"]]
        proof = (
            max(historical, key=lambda p: (p["covered_to"], p["proof_id"])) if historical else None
        )
        selected, _ = _selected_sources(session, account)
        metadata = _identities([view for _, view, error in selected if not error and view])
        result = returns_view._investment_report_result(proof) if proof else None
        status = proof["status"] if proof else "absent"
        reasons = list(proof["reason_codes"]) if proof else ["all_history_source_proof_absent"]
        analyses = captured.get(proof["proof_id"], {}) if proof and status == "current" else {}
        source_names = (
            source_investment_proofs.read_report_display_names(
                session, source_account=account, proof_id=proof["proof_id"]
            )
            if proof and status == "current"
            else {}
        )
        keys = sorted(analyses) if status == "current" else sorted(metadata)
        prototypes = [
            SimpleNamespace(
                isin=isin,
                source_name=next(iter(observed))
                if len(observed := metadata[isin]["names"] | set(source_names.get(isin, ()))) == 1
                else None,
            )
            for isin in keys
        ]
        names = returns_view._catalogue_names(session, prototypes)
        period = result["period"] if result else None
        for row in prototypes:
            meta = metadata[row.isin]
            if row.isin in analyses:
                row.analysis = analyses[row.isin]
                row.instrument_type = next(iter(meta["types"])) if len(meta["types"]) == 1 else None
                instrument = returns_view._instrument(
                    row, row.analysis.opening_date, row.analysis.closing_date, names
                )
                item = {
                    key: instrument[key]
                    for key in ("period", "pnl", "rate", "coupons", "dividends")
                }
                name, kind = instrument["name"], instrument["kind"]
            else:
                # Metadata can survive an unavailable proof; no older numbers
                # or current catalogue values are substituted for its operands.
                item = {
                    "period": period,
                    "pnl": _unknown("all_history_source_proof_unavailable"),
                    "rate": _unknown("all_history_source_proof_unavailable", rate=True),
                    "coupons": _unknown("all_history_source_proof_unavailable"),
                    "dividends": _unknown("all_history_source_proof_unavailable"),
                }
                name = row.source_name or names.get(row.isin) or row.isin
                kind = next(iter(meta["types"])) if len(meta["types"]) == 1 else None
            grouped[row.isin].append(
                {"scope": scope, "label": labels[scope], "name": name, "kind": kind, **item}
            )
        accounts.append(
            {
                "scope": scope,
                "label": labels[scope],
                "period": period,
                "result": result,
                "proof_status": status,
                "reason_codes": reasons,
                "instrument_count": len(keys),
            }
        )
    instruments = []
    for isin, rows in sorted(grouped.items()):
        names = {r["name"] for r in rows if r["name"] != isin}
        kinds = {r["kind"] for r in rows if r["kind"] is not None}
        instruments.append(
            {
                "isin": isin,
                "name": next(iter(names)) if len(names) == 1 else isin,
                "kind": next(iter(kinds)) if len(kinds) == 1 else None,
                "accounts": [
                    {key: value for key, value in row.items() if key not in {"name", "kind"}}
                    for row in rows
                ],
                "reason_codes": ["instrument_name_conflict"]
                if len(names) > 1
                else ([] if names else ["instrument_name_unavailable"]),
            }
        )
    return accounts, instruments, canonical


def _account_mappings(session, canonical):
    """Exact accepted identity metadata; never a name/amount join."""
    mappings = defaultdict(set)
    for alias, account_id in session.execute(
        select(
            BrokerIdentityMapping.provider_identity, BrokerIdentityMapping.hermes_account_id
        ).where(
            BrokerIdentityMapping.provider == PROVIDER,
            BrokerIdentityMapping.subject_kind == "account",
            BrokerIdentityMapping.status == "effective",
        )
    ):
        if alias in canonical:
            mappings[canonical[alias]].add(account_id)
    reverse = defaultdict(set)
    for native, identities in mappings.items():
        for identity in identities:
            reverse[identity].add(native)
    return mappings, reverse


def _identity_conflict(native, mappings, reverse):
    return len(mappings[native]) > 1 or any(len(reverse[a]) > 1 for a in mappings[native])


def _coupon_income(accounts, mappings, reverse):
    """Known credited account coupons once, independent of valuation/P&L.

    These are latest current exact whole-history account operands. Instrument
    explanations, monthly overlap, forecasts and accepted copies are not addends.
    """
    rows, values, seen = [], [], set()
    for account in accounts:
        native = account["scope"].removeprefix("source:")
        if native in seen:
            continue
        seen.add(native)
        amount = (
            account["result"]["coupons"]
            if account["result"]
            else _unknown("all_history_source_proof_absent")
        )
        reasons = list(dict.fromkeys([*account["reason_codes"], *amount["reason_codes"]]))
        if _identity_conflict(native, mappings, reverse):
            excluded = "source_account_identity_mapping_conflict"
        elif account["proof_status"] != "current":
            excluded = "current_coupon_history_unavailable"
        elif amount["value"] is None:
            excluded = "coupon_income_unavailable"
        else:
            excluded = None
            values.append(int(amount["value"]))
        rows.append(
            {
                "scope": account["scope"],
                "label": account["label"],
                "period": account["period"],
                "amount": amount,
                "proof_status": account["proof_status"],
                "included": excluded is None,
                "exclusion_reason": excluded,
                "reason_codes": list(dict.fromkeys([*reasons, *([excluded] if excluded else [])])),
            }
        )
    reasons = ["known_source_history_coupons_only", "source_only_not_financial_close"]
    if any(not row["included"] for row in rows):
        reasons.append("coupon_history_accounts_missing_or_excluded")
    if (
        len(
            {
                (row["period"]["start"], row["period"]["end"])
                for row in rows
                if row["included"] and row["period"]
            }
        )
        > 1
    ):
        reasons.append("coupon_account_history_periods_differ")
    return {
        "known_total": returns_view.metric(
            sum(values) if values else None, reasons=reasons, method="known_source_history_coupons"
        ),
        "partial": True,
        "selected_accounts": len(rows),
        "included_accounts": len(values),
        "accounts": rows,
        "reason_codes": reasons,
    }


def _mixed_result(session, accounts, gold, months, mappings, reverse):
    """Distinct supported operands; no account-plus-explanation or stale fallback."""
    components, included_native = [], []

    def component(identity, category, label, amount, interval, valuation_date, authority, reasons):
        return {
            "id": identity,
            "category": category,
            "label": label,
            "selected": True,
            "available": amount["value"] is not None,
            "included": False,
            "amount": amount,
            "interval": interval,
            "valuation_date": valuation_date,
            "coverage": {
                "status": "partial" if amount["value"] is not None else "unavailable",
                "reason_codes": list(dict.fromkeys(reasons)),
            },
            "method": amount["method"],
            "authority": authority,
            "exclusion_reason": None,
        }

    for account in accounts:
        native = account["scope"].removeprefix("source:")
        amount = (
            account["result"]["pnl"]
            if account["result"]
            else _unknown("all_history_source_proof_absent")
        )
        row = component(
            account["scope"],
            "brokerage",
            account["label"],
            amount,
            account["period"],
            None,
            "source_only",
            account["reason_codes"],
        )
        conflicting = _identity_conflict(native, mappings, reverse)
        if conflicting:
            row["coverage"]["status"] = "conflict"
            row["exclusion_reason"] = "source_account_identity_mapping_conflict"
        elif account["proof_status"] != "current" or not row["available"]:
            row["exclusion_reason"] = "current_whole_history_result_unavailable"
        else:
            row["included"] = True
            included_native.append(native)
        components.append(row)

    unresolved = any(len(mappings[native]) != 1 for native in included_native)
    covered_accounts = {a for native in included_native for a in mappings[native]}
    snapshot_accounts = defaultdict(list)

    def include_snapshot(row, account_id):
        if not row["available"]:
            row["exclusion_reason"] = "snapshot_component_unavailable"
        elif unresolved:
            row["exclusion_reason"] = "source_snapshot_overlap_unproven"
        elif account_id in covered_accounts:
            row["exclusion_reason"] = "snapshot_account_already_covered_by_source"
        else:
            row["included"] = True
        components.append(row)
        snapshot_accounts[account_id].append(row)

    month_by_id = {month.id: month for month in months}
    deposits = defaultdict(list)
    for snapshot, account in session.execute(
        select(DepositSnapshot, Account)
        .join(Account, Account.id == DepositSnapshot.account_id)
        .order_by(DepositSnapshot.id)
    ):
        deposits[account.id].append((snapshot, account))
    for account_id, rows in deposits.items():
        known = [
            (s, month_by_id[s.reporting_month_id])
            for s, _ in rows
            if s.reporting_month_id in month_by_id
            and month_by_id[s.reporting_month_id].status == "closed"
        ]
        amount = returns_view.metric(
            sum(s.actual_interest_received_kopecks for s, _ in known) if known else None,
            reasons=("known_received_interest_only", "deposit_full_history_not_proven"),
            method="deposit_received_interest",
            estimate=False,
        )
        interval = (
            returns_view.bounds(
                min(m.period_start for _, m in known) - timedelta(days=1),
                max(m.period_end for _, m in known),
            )
            if known
            else None
        )
        row = component(
            f"deposit:{account_id}",
            "deposits",
            rows[0][1].name,
            amount,
            interval,
            None,
            "accepted_snapshot",
            amount["reason_codes"],
        )
        include_snapshot(row, account_id)
    for snapshot in gold["snapshots"]:
        amount = {**snapshot["unrealized_result"], "method": "saved_snapshot_unrealized"}
        row = component(
            f"gold:{snapshot['account_id']}:{snapshot['instrument_id']}",
            "gold",
            snapshot["label"],
            amount,
            None,
            snapshot["date"],
            "accepted_snapshot",
            amount["reason_codes"],
        )
        include_snapshot(row, snapshot["account_id"])
    for rows in snapshot_accounts.values():
        if len({row["category"] for row in rows}) > 1:
            for row in rows:
                if row["included"]:
                    row["included"] = False
                    row["exclusion_reason"] = "canonical_snapshot_overlap_unproven"
    included = [int(row["amount"]["value"]) for row in components if row["included"]]
    reasons = ["partial_mixed_result_not_portfolio_pnl", "unknown_components_may_reduce_result"]
    return {
        "known_result": returns_view.metric(
            sum(included) if included else None,
            reasons=reasons,
            method="known_nonoverlapping_components",
        ),
        "rate": _unknown("mixed_component_periods_and_flows_not_unified", rate=True),
        "selected_component_count": len(components),
        "available_component_count": sum(row["available"] for row in components),
        "included_component_count": len(included),
        "components": components,
        "reason_codes": reasons,
    }


def read_overall(session):
    with source_read_snapshot(session):
        months = returns_view._months(session)
        accounts, instruments, canonical = _source_accounts(session)
        mappings, reverse = _account_mappings(session, canonical)
        for instrument in instruments:
            for account in instrument["accounts"]:
                native = account["scope"].removeprefix("source:")
                account["canonical_account_id"] = (
                    next(iter(mappings[native]))
                    if len(mappings[native]) == 1
                    and not _identity_conflict(native, mappings, reverse)
                    else None
                )
        gold = _gold(session, months)
        return {
            "contract_version": "returns_overall_v1",
            "overall": {
                "pnl": _unknown("overall_aggregation_pending_review"),
                "rate": _unknown("overall_aggregation_pending_review", rate=True),
                "partial": True,
                "reason_codes": ["overall_aggregation_pending_review"],
            },
            "source_accounts": accounts,
            "instruments": instruments,
            "deposits": _deposits(session, months),
            "gold": gold,
            "mixed_result": _mixed_result(session, accounts, gold, months, mappings, reverse),
            "coupon_income": _coupon_income(accounts, mappings, reverse),
            "reason_codes": [
                "source_only_not_financial_close",
                "overall_aggregation_pending_review",
            ],
        }
