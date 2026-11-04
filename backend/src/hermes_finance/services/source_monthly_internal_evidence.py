"""Narrow, read-only reuse of current historical account evidence."""

from hermes_finance.services.source_money_classifications import source_reference


def _matching_group(observations, views, native_scope):
    """Require one unchanged, default-classified occurrence per covering source."""
    if not observations or len(native_scope or ()) != 1:
        return None
    first = observations[0]
    if any(
        flow.classification != "unknown"
        or flow.status != "assumed"
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
        ) != ("default_rule", "assumed", "unknown"):
            return None
        # A differing timestamp or a duplicate within one source is ambiguous.
        signature = {k: v for k, v in row.items() if k != "ordinal"}
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

    if any(error or not view for _, view, error in selected):
        return set(), set()
    views = [view for _, view, _ in selected]
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
        proof = redemptions.get(f"money:{key[0]}:{key[1]}")
        roles = set()
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
        if len(roles) == 1 and "blocked" not in roles:
            resolved.add(key)
            if roles == {"redemption"}:
                resolved_scopes.update(
                    (view["id"], flow.event_date.replace(day=1))
                    for view, _, _ in members
                    if scopes.get((view["id"], flow.event_date.replace(day=1))) == proof.isin
                )
    return resolved, resolved_scopes
