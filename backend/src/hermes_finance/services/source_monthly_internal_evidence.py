"""Narrow, read-only reuse of current historical account evidence."""

from hermes_finance.services.source_money_classifications import source_reference


def _matching_group(observations, views, native_scope):
    """Require one unchanged, default-classified occurrence per covering source."""
    if not observations or len(native_scope or ()) != 1:
        return None
    first = observations[0]
    if any(
        flow.classification != "unknown"
        or flow.status not in {"assumed", "confirmed"}
        or flow.event_date != first.event_date
        or flow.amount_kopecks != first.amount_kopecks
        or len(flow.source_references) != 1
        for flow in observations
    ):
        return None
    covering = [v for v in views if v["covered_from"] <= str(first.event_date) <= v["covered_to"]]
    refs = {flow.source_references[0] for flow in observations}
    if len(refs) != len(observations) or len(covering) != len(observations):
        return None
    found, signatures = [], []
    for view in covering:
        rows = [
            row
            for row in view["document"].get("money", [])
            if source_reference(view["id"], row) in refs
        ]
        if len(rows) != 1 or rows[0].get("source_account") not in native_scope:
            return None
        row = rows[0]
        ref = source_reference(view["id"], row)
        choices = [c for c in view["money_classifications"] if c["source_reference"] == ref]
        if len(choices) != 1 or (
            choices[0]["origin"],
            choices[0]["status"],
            choices[0]["classification"],
        ) not in {("default_rule", "assumed", "unknown"), ("user_choice", "confirmed", "unknown")}:
            return None
        # Timestamp differences require independent current evidence below.
        signature = {k: v for k, v in row.items() if k not in {"ordinal", "last_update"}}
        if (
            sum(
                {k: v for k, v in r.items() if k not in {"ordinal", "last_update"}}
                == {k: v for k, v in signature.items() if k != "last_update"}
                for r in view["document"].get("money", [])
            )
            != 1
        ):
            return None
        found.append((view, row, ref))
        signatures.append(signature)
    if any(sig != signatures[0] for sig in signatures[1:]):
        return None
    return found


def verified_internal_money(
    session,
    source_account,
    selected,
    native_scope,
    cancellation_dates,
    money,
    *,
    include_xirr=False,
):
    """Return exact groups and scoped cancellations backed by current proofs."""
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_redemption_evidence import verified_redemptions
    from hermes_finance.services.source_return_evidence import _source_allows_payout

    unavailable = [(o.covered_from, o.covered_to) for o, v, error in selected if error or not v]
    views = [view for _, view, error in selected if view and not error]
    groups = {
        key: members
        for key, observations in money.items()
        if (members := _matching_group(observations, views, native_scope)) is not None
    }
    if not groups:
        return set(), set()
    reports = proofs.read_reports(session, source_account=source_account, include_xirr=include_xirr)
    scopes, redemptions = verified_redemptions(
        session, source_account, selected, native_scope, cancellation_dates
    )
    resolved, resolved_scopes = set(), set()
    for key, members in groups.items():
        flow = money[key][0]
        if any(start <= flow.event_date <= end for start, end in unavailable):
            continue
        proof = redemptions.get(f"money:{key[0]}:{key[1]}")
        roles = set()
        attested = set()
        differing_stamps = len({r.get("last_update") for _, r, _ in members}) > 1
        if (
            proof is not None
            and proof.event_date == flow.event_date
            and len(proof.cash_legs) == 1
            and proof.cash_legs[0].account_cash_kopecks == flow.amount_kopecks
        ):
            roles.add(
                "redemption"
                if all(_source_allows_payout(session, view, proof.isin) for view, _, _ in members)
                else "blocked"
            )
            attested.update(
                ref
                for v, r, ref in members
                if f"{v['document_sha256']}:money:{r['ordinal']}" in proof.source_references
            )
        for report in reports:
            if report["status"] != "current" or not report["interval"]:
                continue
            if not report["covered_from"] <= str(flow.event_date) <= report["covered_to"]:
                continue
            for item in report["interval"].get("account_only", []):
                if item.get("kind") != "unallocated_compensation" or str(
                    flow.amount_kopecks
                ) != item.get("amount_kopecks"):
                    continue
                if any(
                    item.get("reference") == f"{v['document_sha256']}:money:{r['ordinal']}"
                    for v, r, _ in members
                ):
                    roles.add("compensation")
                    attested.update(
                        ref
                        for v, r, ref in members
                        if item.get("reference") == f"{v['document_sha256']}:money:{r['ordinal']}"
                    )
        if differing_stamps and attested != {ref for _, _, ref in members}:
            continue
        if len(roles) == 1 and "blocked" not in roles:
            resolved.add(key)
            if roles == {"redemption"}:
                resolved_scopes.update(
                    (view["id"], flow.event_date.replace(day=1))
                    for view, _, _ in members
                    if scopes.get((view["id"], flow.event_date.replace(day=1))) == proof.isin
                )
    return resolved, resolved_scopes


def apply_verified_compensations(session, source_account, selected, events):
    """Explain proven account income without assigning it to an instrument."""
    from dataclasses import replace

    from hermes_finance.services import source_investment_proofs as proofs

    references = {}
    for _, view, error in selected:
        if error or not view:
            continue
        for row in view["document"].get("money", []):
            references[source_reference(view["id"], row)] = (
                f"{view['document_sha256']}:money:{row['ordinal']}"
            )
    amounts = {}
    for report in proofs.read_reports(session, source_account=source_account, include_xirr=False):
        if report["status"] != "current" or not report["interval"]:
            continue
        for item in report["interval"].get("account_only", []):
            if item.get("kind") == "unallocated_compensation":
                amounts.setdefault(item.get("reference"), set()).add(item.get("amount_kopecks"))
    result = []
    for event in events:
        if (
            event.kind == "UNRESOLVED"
            and event.classification == "unknown"
            and event.isin is None
            and len(event.cash_legs) == 1
            and event.source_references
            and (event.classification_origin, event.classification_status)
            in {("default_rule", "assumed"), ("user_choice", "confirmed")}
            and "unrecognized_money" in event.reason_codes
            and set(event.reason_codes) <= {"unrecognized_money", "payout_classification_conflict"}
            and all(
                amounts.get(references.get(ref)) == {str(event.cash_legs[0].account_cash_kopecks)}
                for ref in event.source_references
            )
        ):
            event = replace(
                event,
                reason_codes=("unallocated_compensation",),
                attribution_basis="current_account_compensation_proof",
            )
        result.append(event)
    return tuple(result)
