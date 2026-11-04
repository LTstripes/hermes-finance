"""Read-only bridge to current, exact-original financial section/Money proof.

No classification, financial fact or receipt is written by a return reader.
"""

import json

from sqlalchemy import select

from hermes_finance.persistence import MyBrokerImport
from hermes_finance.services.mybroker_money_candidates import _original_equal
from hermes_finance.statement_import.mybroker import digest


def bound_import(session, view):
    source = session.scalar(
        select(MyBrokerImport).where(MyBrokerImport.document_sha256 == view["document_sha256"])
    )
    if source is None:
        return None
    document = view["document"]
    if (
        source.parser_version != document["parser"]
        or str(source.covered_from) != view["covered_from"]
        or str(source.covered_to) != view["covered_to"]
        # S1 enriches parsed facts with account/cash linkage. Compare the frozen
        # parser facts, as other exact-original readers do, rather than that enrichment.
        or not _original_equal(document, json.loads(source.normalized_json))
    ):
        return None
    return source


def effective_bonus(session, source, row):
    """Only the exact reviewed bonus occurrence, never a nearby or matching sum."""
    if source is None:
        return False
    from hermes_finance.services import broker_money as money

    target_id = f"{source.id}:{row['ordinal']}"
    entry = money.latest_proofs(session).get(("broker_bonus", target_id))
    if entry is None:
        return False
    receipt, proof, target = entry
    return any(
        occurrence["import_id"] == source.id
        and occurrence["section"] == "money"
        and occurrence["ordinal"] == row["ordinal"]
        and occurrence["row_fingerprint"] == digest(row)
        and occurrence["role"] == "broker_bonus"
        and occurrence["target_id"] == target_id
        for occurrence in proof["occurrences"]
    ) and not money.proof_blockers(session, receipt, proof, target)


def payout_source_unambiguous(views, view, event_date):
    """Only use a receipt directly when no other selected source covers the date."""
    day = str(event_date)
    covered = [v for v in views if v["covered_from"] <= day <= v["covered_to"]]
    return len(covered) == 1 and covered[0]["id"] == view["id"]


def effective_overlapping_payout(session, views, view, row, saved, resolver):
    """Project one current receipt only across uniquely identical source rows."""
    from hermes_finance.services.source_money_classifications import source_reference

    day = str(row.get("date"))
    covering = [v for v in views if v["covered_from"] <= day <= v["covered_to"]]
    if len(covering) < 2 or view["id"] not in {v["id"] for v in covering}:
        return None
    relevant = (
        "classification",
        "operation",
        "narrative",
    )
    if saved.get("origin") not in {"default_rule", "user_choice"}:
        return None
    signature = {k: v for k, v in row.items() if k not in {"ordinal", "last_update"}}
    matches = []
    for candidate in covering:
        raw = [
            r
            for r in candidate["document"].get("money", [])
            if {k: v for k, v in r.items() if k not in {"ordinal", "last_update"}} == signature
        ]
        if len(raw) != 1:
            return None
        ref = source_reference(candidate["id"], raw[0])
        choices = [
            r for r in candidate["money_classifications"] if r.get("source_reference") == ref
        ]
        if (
            len(choices) != 1
            or choices[0].get("origin") not in {"default_rule", "user_choice"}
            or any(choices[0].get(k) != saved.get(k) for k in relevant)
        ):
            return None
        matches.append((candidate, raw[0], choices[0]))
    proven = [
        value
        for v, r, s in matches
        if (value := effective_payout_match(session, v, r, s, resolver, allow_multiple=True))
        is not None
    ]
    identities = {(p[0], p[1], p[2], p[3]) for p in proven}
    if len(identities) != 1:
        return None
    # Different original timestamps are safe only when each distinct row is
    # itself owned and verified by the same current accepted receipt.
    if len({r.get("last_update") for _, r, _ in matches}) > 1 and len(proven) != len(matches):
        return None
    isin, _, _, _ = next(iter(identities))
    if any(not _payout_choice_agrees(s, resolver, isin) for _, _, s in matches):
        return None
    # Every observation in the receipt must correspond to one exact member of
    # this group; identical amounts or ISINs alone never collapse targets.
    group_keys = set()
    for candidate, raw, _ in matches:
        source = bound_import(session, candidate)
        if source is not None:
            group_keys.add((source.id, "money", raw["ordinal"], digest(raw)))
    if any(not p[4].issubset(group_keys) for p in proven):
        return None
    return isin if all(_source_allows_payout(session, v, isin) for v, _, _ in matches) else None


def _payout_choice_agrees(saved, resolver, isin):
    if saved.get("instrument_link_status") == "linked":
        from hermes_finance.services.source_instrument_events import payout_attribution

        linked, _, reasons = payout_attribution(saved, resolver, {})
        return linked == isin and not reasons
    return saved.get("instrument_id") is None and saved.get("instrument_link_status") in {
        None,
        "not_parsed",
        "unresolved_no_match",
    }


def effective_payout_instrument(session, view, row, saved, resolver):
    """Use an exact current Money receipt, without altering intake decisions."""
    match = effective_payout_match(session, view, row, saved, resolver)
    return match[0] if match else None


def effective_payout_match(
    session, view, row, saved, resolver, *, allow_multiple=False, check_choice=True
):
    """Return exact receipt identity for read-only group reconciliation."""
    from hermes_finance.statement_import.mybroker import MyBrokerError

    try:
        return _effective_payout_instrument(
            session,
            view,
            row,
            saved,
            resolver,
            allow_multiple=allow_multiple,
            check_choice=check_choice,
        )
    except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
        return None


def _payout_money_heads(session):
    from hermes_finance.database import snapshot_read_result
    from hermes_finance.services import broker_money as money

    return snapshot_read_result(
        session, "source_payout_money_heads", (), lambda: money.latest_proofs(session)
    )


def _source_allows_payout(session, view, isin):
    """An unbound original adds no authority; explicit excluded/stale imports block it."""
    from hermes_finance.database import snapshot_read_result
    from hermes_finance.services.mybroker_dispositions import resolve

    source = bound_import(session, view)
    if source is None:
        return (
            session.scalar(
                select(MyBrokerImport).where(
                    MyBrokerImport.document_sha256 == view["document_sha256"]
                )
            )
            is None
        )
    dispositions = snapshot_read_result(
        session, "source_payout_dispositions", source.id, lambda: resolve(session, source)
    )
    return not any(
        item["isin"] == isin and item["effective_state"] != "mapped" for item in dispositions
    )


def _effective_payout_instrument(
    session, view, row, saved, resolver, *, allow_multiple=False, check_choice=True
):
    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services import broker_money as money
    from hermes_finance.services.broker_money_ownership import owners
    from hermes_finance.services.broker_statement_provisional import _minor
    from hermes_finance.services.source_money_classifications import source_reference

    role = saved.get("classification")
    if (
        role not in {"coupon", "dividend"}
        or saved.get("origin") not in {"default_rule", "user_choice"}
        or saved.get("instrument_link_status")
        not in {None, "not_parsed", "unresolved_no_match", "linked"}
        or saved.get("source_reference") != source_reference(view["id"], row)
    ):
        return None
    source = bound_import(session, view)
    if source is None:
        return None
    occurrence = {"import_id": source.id, "section": "money", "ordinal": row["ordinal"]}
    owned = owners(session, [occurrence])
    if len(owned) != 1:
        return None
    owner = owned[0]
    if owner["role"] != role or owner["row_fingerprint"] != digest(row):
        return None
    heads = _payout_money_heads(session)
    entry = heads.get((role, owner["target_id"]))
    if entry is None:
        return None
    receipt, proof, target = entry
    cohort = [
        o for o in proof["occurrences"] if (o["role"], o["target_id"]) == (role, owner["target_id"])
    ]
    own_matches = [o for o in cohort if all(o.get(k) == v for k, v in occurrence.items())]
    if len(own_matches) != 1 or (len(cohort) != 1 and not allow_multiple):
        return None
    if own_matches[0]["row_fingerprint"] != digest(row) or money.proof_blockers(
        session, receipt, proof, target
    ):
        return None
    cohort_keys = {
        (o["import_id"], o["section"], o["ordinal"], o["row_fingerprint"]) for o in cohort
    }
    if len(cohort_keys) != len(cohort):
        return None
    all_owners = owners(session, cohort)
    if (
        len(all_owners) != len(cohort)
        or {
            (*o["key"], o["row_fingerprint"])
            for o in all_owners
            if o["role"] == role and o["target_id"] == owner["target_id"]
        }
        != cohort_keys
    ):
        return None
    facts = target.get("facts") or {}
    month = session.get(ReportingMonth, receipt.reporting_month_id)
    instrument_id = facts.get("instrument_id")
    instrument = resolver.instruments.get(int(instrument_id)) if instrument_id is not None else None
    expected_kind = "bond" if role == "coupon" else "stock"
    if (
        not instrument
        or not instrument.isin
        or instrument.instrument_type != expected_kind
        or instrument.currency != "RUB"
        or facts.get("flow_type") != role
        or facts.get("account_id") != str(receipt.account_id)
        or facts.get("reporting_month_id") != str(receipt.reporting_month_id)
        or facts.get("currency") != "RUB"
        or facts.get("event_date") != str(row.get("date"))
        or facts.get("net_amount_kopecks") != str(_minor(row.get("amount")))
        or month is None
        or not month.period_start.isoformat() <= str(row["date"]) <= month.period_end.isoformat()
    ):
        return None
    if check_choice and not _payout_choice_agrees(saved, resolver, instrument.isin):
        return None
    if not _source_allows_payout(session, view, instrument.isin):
        return None
    return instrument.isin, receipt.request_id, role, owner["target_id"], frozenset(cohort_keys)


def apply_cash_gifts(session, view, rows):
    """Project only current exact cash gifts; never mutate saved source rows."""
    source = bound_import(session, view)
    captured = view["money_classifications"]
    raw = view["document"]["money"]
    if len(rows) != len(raw) or len(rows) != len(captured):
        return rows
    result = []
    for value, saved, original in zip(rows, captured, raw, strict=True):
        eligible = (
            saved["classification"] in {"unknown", "external_deposit"}
            and value["minor"] == saved["amount_kopecks"]
            and value["minor"] > 0
            and str(value["day"]) == str(saved["date"])
            and value["currency"] == saved["currency"] == "RUB"
            and effective_bonus(session, source, original)
        )
        result.append({**value, "classification": "external_gift"} if eligible else value)
    return result


def effective_section_blockers(session, source, codes):
    if source is None:
        return set(codes)
    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services.broker_sections import coverage_disposition

    accounts = set(
        session.scalars(
            select(BrokerMonthApply.account_id).where(BrokerMonthApply.import_id == source.id)
        )
    )
    if len(accounts) != 1:
        return set(codes)
    return set(coverage_disposition(session, source, accounts.pop(), codes)["effective_blockers"])


def historical_payout_evidence(session, source_account, selected, native_scope):
    """Reuse current original-bound components, never interior endpoint values.

    Values are exact (intake, ordinal) identities. None is a conflict tombstone,
    not an absent proof. No link/classification/financial row is persisted.
    """
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.broker_statement_provisional import _minor
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.statement_import.money import normalize_currency

    if native_scope is None or len(native_scope) != 1 or any(error for _, _, error in selected):
        return {}
    views = {view["document_sha256"]: view for _, view, _ in selected}
    analyses = {}
    reports = proofs.read_reports(
        session, source_account=source_account, analyses=analyses, include_xirr=False
    )
    current = {r["proof_id"] for r in reports if r["status"] == "current"}
    result = {}
    identity_errors = {
        "payout_identity_ambiguous",
        "pdf_xml_payout_mismatch",
        "pdf_payout_row_invalid",
        "pdf_actual_payout_section_missing",
        "pdf_account_period_invalid",
    }
    for proof, plan in proofs._report_rows(session, source_account):
        view = views.get(plan["source_sha256"])
        if proof.id not in current or view is None:
            continue
        prefix = view["document_sha256"] + ":money:"
        for analysis in analyses.get(proof.id, {}).values():
            for event in analysis.events:
                if (
                    event.kind not in {"COUPON", "DIVIDEND"}
                    or not event.current
                    or not event.counted
                    or event.reason_codes
                    or event.classification_status != "confirmed"
                    or event.native_source_account not in native_scope
                    or not event.isin
                    or event.effective_isin != event.isin
                    or len(event.source_references) != 1
                    or len(event.cash_legs) != 1
                ):
                    continue
                reference = event.source_references[0]
                if not reference.startswith(prefix) or not reference[len(prefix) :].isdigit():
                    continue
                ordinal = int(reference[len(prefix) :])
                rows = [r for r in view["document"]["money"] if r["ordinal"] == ordinal]
                if len(rows) != 1:
                    continue
                row, leg = rows[0], event.cash_legs[0]
                key = source_reference(view["id"], row)
                if (
                    row["source_account"] != event.native_source_account
                    or normalize_currency(row.get("currency")) != "RUB"
                    or row["date"] != str(event.event_date)
                    or leg.date != event.event_date
                    or _minor(row["amount"]) != leg.account_cash_kopecks
                    or leg.account_cash_kopecks <= 0
                    or event.net_payout_kopecks != leg.account_cash_kopecks
                    or leg.instrument_flow_kopecks != -leg.account_cash_kopecks
                    or event.classification != event.kind.lower()
                ):
                    continue
                value = (
                    event.isin,
                    event.classification,
                    str(event.event_date),
                    leg.account_cash_kopecks,
                    event.native_source_account,
                )
                if identity_errors.intersection(analysis.reason_codes):
                    result[key] = None
                elif key in result and result[key] != value:
                    result[key] = None
                else:
                    result[key] = value
    return result


def effective_historical_payout(session, views, view, row, saved, resolver, evidence):
    """One exact source group may reuse an agreed current historical payout.

    Return (ISIN, conflict). A failed proof never manufactures Money authority.
    """
    from hermes_finance.services.source_money_classifications import source_reference

    if not evidence or saved.get("classification") not in {"coupon", "dividend"}:
        return None, False
    covering = [v for v in (views or [view]) if v["covered_from"] <= row["date"] <= v["covered_to"]]
    signature = {k: v for k, v in row.items() if k not in {"ordinal", "last_update"}}
    matches = []
    for candidate in covering:
        rows = [
            r
            for r in candidate["document"].get("money", [])
            if {k: v for k, v in r.items() if k not in {"ordinal", "last_update"}} == signature
        ]
        if len(rows) != 1:
            return None, False
        ref = source_reference(candidate["id"], rows[0])
        choices = [c for c in candidate["money_classifications"] if c["source_reference"] == ref]
        if len(choices) != 1:
            return None, False
        matches.append((candidate, rows[0], choices[0], ref))
    known = [evidence[ref] for _, _, _, ref in matches if ref in evidence]
    if not known:
        return None, False
    if None in known or len(set(known)) != 1:
        return None, True
    isin, role, day, amount, account = known[0]
    if role != saved["classification"]:
        return None, True
    # A different original timestamp is not the same attested occurrence unless
    # each original carries independently current exact-reference evidence.
    if len({r.get("last_update") for _, r, _, _ in matches}) > 1 and len(known) != len(matches):
        return None, False
    money_proofs = []
    group_keys = set()
    for candidate, raw, choice, _ in matches:
        if (
            choice.get("origin") not in {"default_rule", "user_choice"}
            or any(
                choice.get(k) != saved.get(k) for k in ("classification", "operation", "narrative")
            )
            or not _payout_choice_agrees(choice, resolver, isin)
            or not _source_allows_payout(session, candidate, isin)
        ):
            return None, True
        # Inspect a current Money receipt independently of saved link agreement:
        # its different instrument is a conflict, never a reason to prefer a proof.
        money = effective_payout_match(
            session, candidate, raw, choice, resolver, allow_multiple=True, check_choice=False
        )
        source = bound_import(session, candidate)
        if source is not None:
            group_keys.add((source.id, "money", raw["ordinal"], digest(raw)))
        if money is not None:
            if money[0] != isin:
                return None, True
            money_proofs.append(money)
    if len({p[:4] for p in money_proofs}) > 1 or any(
        not p[4].issubset(group_keys) for p in money_proofs
    ):
        return None, True
    return isin, False
