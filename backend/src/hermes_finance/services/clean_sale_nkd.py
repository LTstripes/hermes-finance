"""Reconcile separate sale NKD at issue/day scope without inventing row ownership."""

from collections import defaultdict
from dataclasses import replace


def _source_ids(references, prefix):
    ids = set()
    for reference in references:
        parts = reference.split(":")
        if len(parts) < 3 or parts[0] != prefix or not parts[1].isdigit():
            return set()
        ids.add(int(parts[1]))
    return ids


def _current_owned_cohort(session, sales, rows, raw, owned):
    """Reuse only the same complete, currently effective permanent cohort."""
    from hermes_finance.services import broker_money as money
    from hermes_finance.services.source_return_evidence import bound_import
    from hermes_finance.statement_import.mybroker import digest

    selected = {}
    group_ids = set()
    for row in rows:
        for ref in row.source_references:
            view, native = raw[ref]
            source = bound_import(session, view)
            if source is None:
                continue
            key = (source.id, "money", native["ordinal"])
            selected[key] = digest(native)
            claim = owned.get(ref, ())
            if not claim:
                continue
            # Reaffirmations repeat the same permanent group claim in the
            # receipt journal. They are one owner, not extra cash occurrences.
            claims = {(c["role"], c["target_id"], c["row_fingerprint"]) for c in claim}
            if (
                len(claims) != 1
                or next(iter(claims))[0] != "trade_group"
                or next(iter(claims))[2] != digest(native)
            ):
                return False
            group_ids.add(next(iter(claims))[1])
    if len(group_ids) != 1:
        return False
    group_id = next(iter(group_ids))
    identities = sorted(sale.native_identity for sale in sales)
    latest = money.latest_proofs(session)
    for receipt, proof in money.receipts(session):
        if proof.get("contract_version") != money.CONTRACT_V3 or proof.get("operation") == "retire":
            continue
        for group in proof.get("statement_groups", ()):
            if group.get("group_id") != group_id:
                continue
            occurrences = group["occurrences"]
            keys = [(o["import_id"], o["section"], o["ordinal"]) for o in occurrences]
            expected = {
                key: value for key, value in selected.items() if key[0] == group["import_id"]
            }
            if (
                group_id != digest([group["import_id"], group["cohort_digest"]])
                or sorted(group["trade_identities"]) != identities
                or len(keys) != len(set(keys))
                or set(keys) != set(expected)
                or any(
                    o["row_fingerprint"] != expected[key]
                    for key, o in zip(keys, occurrences, strict=True)
                )
                or group["source_account"] != sales[0].native_source_account
                or group["date"] != sales[0].cash_settlement_date.isoformat()
                or group["currency"] != "RUB"
                or group["native_total_basis"] != "includes_paid_nkd"
                or any(sale.accrued_interest_kopecks != group["signed_nkd_minor"] for sale in sales)
            ):
                continue
            targets = [
                t
                for t in proof["targets"]
                if t["role"] == "trade"
                and t.get("cash_proof", {}).get("cohort", {}).get("group_id") == group_id
            ]
            if sorted(t["cash_proof"]["source_identity"] for t in targets) != identities:
                continue
            entries = [latest.get(("trade", t["target_id"])) for t in targets]
            if entries and all(
                entry
                and entry[0].request_id == receipt.request_id
                and not money.proof_blockers(session, *entry)
                for entry in entries
            ):
                return True
    return False


def reconcile_sale_nkd(session, events, views):
    """Only exact positive RUB principal + explicit NKD = native dirty total.

    A multi-sale cohort proves the sum, not which NKD belongs to an execution.
    Native per-trade totals remain the sole per-execution amounts.
    """
    from hermes_finance.services.broker_money_ownership import owners
    from hermes_finance.services.source_money_classifications import _is_nkd, source_reference
    from hermes_finance.services.source_return_evidence import _source_allows_payout, bound_import
    from hermes_finance.statement_import.money import normalize_currency

    by_id = {view["id"]: view for view in views}
    raw = {
        source_reference(view["id"], row): (view, row)
        for view in views
        for row in view["document"].get("money", ())
    }
    choices = {c["source_reference"]: c for view in views for c in view["money_classifications"]}
    trades, money = defaultdict(list), defaultdict(list)
    replacements = {}
    for event in events:
        key = (event.provider, event.native_source_account, event.isin, event.cash_settlement_date)
        if event.kind == "SELL":
            trades[key].append(event)
            principal = [
                leg
                for leg in event.cash_legs
                if leg.role == "principal" and not leg.ownership.startswith("trade:")
            ]
            if (
                event.provider == "alfa_mybroker"
                and event.price_unit == "PERCENT_OF_FACE"
                and event.native_total_basis == "includes_paid_nkd"
                and event.native_trade_amount_kopecks is not None
                and event.accrued_interest_kopecks is not None
                and event.accrued_interest_kopecks > 0
                and principal
                and sum(leg.account_cash_kopecks for leg in principal)
                == event.native_trade_amount_kopecks - event.accrued_interest_kopecks
                and not any(
                    leg.role == "nkd" and not leg.ownership.startswith("trade:")
                    for leg in event.cash_legs
                )
            ):
                replacements[event.event_key] = replace(
                    event,
                    counted=False,
                    reason_codes=tuple(
                        sorted(set(event.reason_codes) | {"sale_nkd_reconciliation_unproven"})
                    ),
                )
        elif event.nkd_money and event.isin and event.event_date == event.cash_settlement_date:
            money[key].append(event)
    if not money:
        return tuple(replacements.get(event.event_key, event) for event in events)
    candidate_refs = {
        ref for rows in money.values() for row in rows for ref in row.source_references
    }
    occurrences, references = [], {}
    for view in views:
        source = bound_import(session, view)
        if source is None:
            continue
        for row in view["document"].get("money", ()):
            ref = source_reference(view["id"], row)
            if ref not in candidate_refs:
                continue
            occurrences.append(
                {"import_id": source.id, "section": "money", "ordinal": row["ordinal"]}
            )
            references.setdefault((source.id, "money", row["ordinal"]), set()).add(ref)
    owned = defaultdict(list)
    for owner in owners(session, occurrences) if occurrences else ():
        for ref in references.get(tuple(owner["key"]), ()):
            owned[ref].append(owner)
    for key, rows in money.items():
        sales = trades.get(key, ())
        if not sales or key[0] != "alfa_mybroker" or not key[2] or key[3] is None:
            continue
        source_ids = set()
        valid = True
        principals, commissions, native_totals, accrued = [], [], [], []
        for sale in sales:
            linked = [leg for leg in sale.cash_legs if not leg.ownership.startswith("trade:")]
            principal = [leg for leg in linked if leg.role == "principal"]
            commission = [leg for leg in linked if leg.role == "commission"]
            ids = _source_ids(sale.source_references, "trade")
            if (
                not sale.current
                or set(sale.reason_codes) - {"trade_money_cash_conflict"}
                or not sale.native_identity
                or len(sale.native_ids) != 2
                or sale.price_unit != "PERCENT_OF_FACE"
                or sale.quantity_delta is None
                or sale.quantity_delta >= 0
                or sale.native_total_basis != "includes_paid_nkd"
                or sale.native_trade_amount_kopecks is None
                or sale.accrued_interest_kopecks is None
                or sale.accrued_interest_kopecks <= 0
                or len(principal) != 1
                or any(leg.role not in {"principal", "commission"} for leg in linked)
                or any(leg.date != key[3] or leg.account_cash_kopecks <= 0 for leg in principal)
                or any(_source_ids(leg.source_references, "money") != ids for leg in principal)
                or (
                    commission
                    and (
                        sale.commission_kopecks is None
                        or any(
                            leg.date != key[3] or leg.account_cash_kopecks > 0 for leg in commission
                        )
                        or sum(leg.account_cash_kopecks for leg in commission)
                        != -sale.commission_kopecks
                    )
                )
                or not ids
                or (source_ids and source_ids != ids)
                or sale.execution_date is None
                or sale.execution_date > key[3]
                or sale.depository_settlement_date != key[3]
            ):
                valid = False
                break
            for source_id in ids:
                view = by_id.get(source_id)
                source_trades = (
                    [
                        t
                        for t in view["document"].get("trades", ())
                        if t.get("identity") == sale.native_identity
                    ]
                    if view
                    else []
                )
                if len(source_trades) != 1 or (
                    source_trades[0]["core"]["currency"] != "RUB"
                    or source_trades[0]["core"]["source_account"] != key[1]
                    or source_trades[0]["core"]["isin"] != key[2]
                    or source_trades[0].get("settlement_date") != key[3].isoformat()
                    or source_trades[0].get("state") != "settled"
                    or source_trades[0].get("repo_observed")
                    or not _source_allows_payout(session, view, key[2])
                ):
                    valid = False
            source_ids = ids
            principals.extend(principal)
            commissions.extend(commission)
            native_totals.append(sale.native_trade_amount_kopecks)
            accrued.append(sale.accrued_interest_kopecks)
        legs = []
        for row in rows:
            if (
                row.kind != "UNRESOLVED"
                or row.reason_codes != ("unmatched_trade_money",)
                or len(row.cash_legs) != 1
                or row.classification != "trade_settlement"
                or _source_ids(row.source_references, "money") != source_ids
            ):
                valid = False
                break
            leg = row.cash_legs[0]
            if (
                leg.account_cash_kopecks <= 0
                or leg.date != key[3]
                or leg.ownership.startswith("trade:")
            ):
                valid = False
            for ref in row.source_references:
                source = raw.get(ref)
                choice = choices.get(ref)
                if (
                    source is None
                    or choice is None
                    or (
                        source[0]["document"]["provider"] != key[0]
                        or source[1]["source_account"] != key[1]
                        or source[1]["date"] != key[3].isoformat()
                        or normalize_currency(source[1]["currency"]) != "RUB"
                        or source[0]["document"]["parser"] != "mybroker-s1-v2"
                        or choice["classification"] != "trade_settlement"
                        or not _is_nkd(choice["operation"] + " " + choice["narrative"])
                        or not _source_allows_payout(session, source[0], key[2])
                    )
                ):
                    valid = False
            legs.append(leg)
        ownerships = [leg.ownership for leg in (*principals, *commissions, *legs)]
        if valid and any(ref in owned for row in rows for ref in row.source_references):
            try:
                valid = _current_owned_cohort(session, sales, rows, raw, owned)
            except (KeyError, TypeError, ValueError, ArithmeticError):
                valid = False
        if (
            not valid
            or len(ownerships) != len(set(ownerships))
            or sum(leg.account_cash_kopecks for leg in principals)
            + sum(leg.account_cash_kopecks for leg in legs)
            != sum(native_totals)
            or sum(leg.account_cash_kopecks for leg in legs) != sum(accrued)
        ):
            continue
        # The cohort cannot prove individual executions unless each printed
        # principal already agrees with that execution's own printed NKD.
        if any(
            principal.account_cash_kopecks + sale.accrued_interest_kopecks
            != sale.native_trade_amount_kopecks
            for sale, principal in zip(sales, principals, strict=True)
        ):
            continue
        basis = "analytical_sale_nkd" if len(sales) == 1 else "analytical_sale_nkd_group"
        for sale in sales:
            cash_legs = sale.cash_legs
            if len(sales) == 1:
                cash_legs = tuple(leg for leg in cash_legs if leg.role != "nkd") + tuple(
                    replace(leg, role="nkd") for leg in legs
                )
            replacements[sale.event_key] = replace(
                sale, counted=True, reason_codes=(), attribution_basis=basis, cash_legs=cash_legs
            )
        for row in rows:
            replacements[row.event_key] = replace(
                row, current=True, counted=False, reason_codes=(), attribution_basis=basis
            )
    return tuple(replacements.get(event.event_key, event) for event in events)
