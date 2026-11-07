"""Read-only bridge to current, exact-original financial section/Money proof.

No classification, financial fact or receipt is written by a return reader.
"""

import json
import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from hermes_finance.database import snapshot_read_result
from hermes_finance.persistence import MyBrokerImport
from hermes_finance.services.mybroker_money_candidates import _original_equal
from hermes_finance.statement_import.mybroker import digest


def bound_import(session, view):
    # Cache only the unique lookup, including absence. Revalidate the supplied
    # view on every call: two callers may hold different document projections.
    source_id = snapshot_read_result(
        session,
        "source_return_bound_import_id",
        view["document_sha256"],
        lambda: session.scalar(
            select(MyBrokerImport.id).where(
                MyBrokerImport.document_sha256 == view["document_sha256"]
            )
        ),
    )
    source = session.get(MyBrokerImport, source_id) if source_id is not None else None
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


def _positive(value):
    try:
        return Decimal(value) > 0
    except (ArithmeticError, TypeError, ValueError):
        return False


def _day_before(day):
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def _issues_held_from_positions(view, account, day):
    """Issues a statement proves were held by the payment, bought there or not."""
    return {
        row.get("isin")
        for row in view["document"].get("positions", [])
        if row.get("source_account") == account
        and (
            (
                _day_before(view["covered_from"]) <= day
                and _positive(row.get("beginning_actual_quantity"))
            )
            or (view["covered_to"] <= day and _positive(row.get("actual_quantity")))
        )
    }


def _issuer_bond_in_account(resolver, security, status, selected, account, day):
    """Find the single catalogue bond of this issuer held in the account by the payment.

    Only a coupon with no identity match qualifies: an ambiguous link is a
    conflict. An issue missing from the catalogue may be another bond of the issuer.
    """
    if status != "unresolved_no_match":
        return None
    issuer = re.sub(r"^(?:ПАО|АО|ООО)\s*", "", security.issuer_name, flags=re.IGNORECASE)
    issuer = " ".join(issuer.strip('"«» ').casefold().split())
    held = {
        trade["core"].get("isin")
        for _, view, error in selected
        if view is not None and not error
        for trade in view["document"].get("trades", [])
        if trade.get("state") == "settled"
        and trade["core"].get("source_account") == account
        and str(trade.get("settlement_date") or "9") <= day
        and _positive(trade["core"].get("quantity"))
    }
    for _, view, error in selected:
        if view is not None and not error:
            held |= _issues_held_from_positions(view, account, day)
    if held - {instrument.isin for instrument in resolver.instruments.values()}:
        return None
    matches = [
        (target, instrument)
        for target, instrument in resolver.instruments.items()
        if instrument.instrument_type == "bond"
        and instrument.isin in held
        and " ".join((instrument.name or "").casefold().split()).startswith(issuer + " ")
    ]
    return matches[0] if issuer and len(matches) == 1 else None


def analytical_coupon_links(session, selected, native_scope, *, historical_evidence=None):
    """Resolve old coupon rows for this read without changing saved decisions.

    Every covering original must contain the same occurrence multiplicity and
    account-bound source facts. A current explicit issue mapping identifies the
    bond. Without one, the issuer may identify it only when it matches exactly
    one catalogue bond bought in this account by the payment date.
    """
    from collections import Counter, defaultdict

    from hermes_finance.domain.money_security import parse_money_security
    from hermes_finance.persistence import BrokerIdentityMapping
    from hermes_finance.services.broker_money_ownership import owners
    from hermes_finance.services.broker_statement_provisional import _minor
    from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.services.source_monthly_returns import _native_scope
    from hermes_finance.statement_import.money import normalize_currency

    if not selected or native_scope is None or len(native_scope) != 1:
        return {}
    if any(original is None for original, _, _ in selected):
        return {}
    if not any(
        choice.get("classification") == "coupon"
        and choice.get("instrument_link_status") == "unresolved_no_match"
        for _, view, error in selected
        if view is not None and not error
        for choice in view["money_classifications"]
    ):
        return {}
    account = next(iter(native_scope))
    resolver = MoneyInstrumentResolver(session)
    usable = {}
    groups = defaultdict(list)
    for original, view, error in selected:
        if (
            error
            or view is None
            or _native_scope(view["document"]) != native_scope
            or view["document"].get("provider") != "alfa_mybroker"
            or view["document"].get("parser") != "mybroker-s1-v2"
            or "period_inferred_from_content" in view["document"].get("warnings", [])
        ):
            continue
        usable[original.id] = view
        saved = {row["source_reference"]: row for row in view["money_classifications"]}
        for row in view["document"].get("money", []):
            ref = source_reference(view["id"], row)
            choice = saved.get(ref)
            if choice is None:
                continue
            signature = digest(
                {k: v for k, v in row.items() if k not in {"ordinal", "last_update"}}
                | {
                    "currency": normalize_currency(row.get("currency")),
                    "operation": choice["operation"],
                    "narrative": choice["narrative"],
                }
            )
            groups[(row["date"], signature)].append((original, view, row, choice, ref))

    result = {}
    for (day, _), members in groups.items():
        if not any(
            c.get("instrument_link_status") == "unresolved_no_match" for _, _, _, c, _ in members
        ):
            continue
        # Existing historical evidence, including a conflict tombstone, has
        # priority over an inferred mapping for the whole occurrence group.
        if historical_evidence and any(ref in historical_evidence for _, _, _, _, ref in members):
            continue
        covering = [o for o, _, _ in selected if str(o.covered_from) <= day <= str(o.covered_to)]
        if not covering or any(original.id not in usable for original in covering):
            continue
        counts = Counter(original.id for original, _, _, _, _ in members)
        if set(counts) != {original.id for original in covering} or len(set(counts.values())) != 1:
            continue
        if len(covering) > 1 and len({row.get("last_update") for _, _, row, _, _ in members}) != 1:
            continue
        first = members[0][3]
        security = parse_money_security(first["narrative"])
        if security is None or security.kind != "coupon":
            continue
        target, status = resolver.resolve(security)
        instrument = resolver.instruments.get(target)
        issuer_match = _issuer_bond_in_account(resolver, security, status, selected, account, day)
        if issuer_match is not None:
            target, instrument = issuer_match
        else:
            if (
                status != "linked"
                or instrument is None
                or instrument.instrument_type != "bond"
                or not instrument.isin
            ):
                continue
            mapped_isin = resolver.reg_isins.get(security.reg_number)
            related = resolver._related(mapped_isin or security.reg_number)
            registration = resolver._related(security.reg_number)
            if (
                (not mapped_isin and not resolver.mapping_targets.get(security.reg_number))
                or (mapped_isin and mapped_isin != instrument.isin)
                or resolver._candidates(related) != {target}
                or related & resolver.conflicts
                or registration & resolver.conflicts
                or not resolver._candidates(registration) <= {target}
            ):
                continue
            bindings = list(
                session.scalars(
                    select(BrokerIdentityMapping).where(
                        BrokerIdentityMapping.provider == "alfa_mybroker",
                        BrokerIdentityMapping.subject_kind == "instrument",
                        BrokerIdentityMapping.provider_identity.in_(related | registration),
                    )
                )
            )
            identities_match = True
            for alias in {row.provider_identity for row in bindings}:
                active = [
                    row
                    for row in bindings
                    if row.provider_identity == alias and row.status == "effective"
                ]
                if len(active) != 1 or active[0].hermes_instrument_id != target:
                    identities_match = False
                    break
            if not identities_match:
                continue
        valid = True
        for _, view, row, choice, ref in members:
            source = bound_import(session, view)
            occurrence = (
                {"import_id": source.id, "section": "money", "ordinal": row["ordinal"]}
                if source is not None
                else None
            )
            if (
                row.get("source_account") != account
                or not view["covered_from"] <= day <= view["covered_to"]
                or normalize_currency(row.get("currency")) != "RUB"
                or normalize_currency(choice.get("currency")) != "RUB"
                or _minor(row.get("amount")) != choice.get("amount_kopecks")
                or choice.get("amount_kopecks") is None
                or choice["amount_kopecks"] <= 0
                or str(choice.get("date")) != day
                or choice.get("classification") != "coupon"
                or choice.get("origin") not in {"default_rule", "user_choice"}
                or choice.get("status") != first.get("status")
                or choice.get("security_reg_number") != security.reg_number
                or choice.get("security_issuer") != security.issuer_name
                or not (
                    (
                        choice.get("instrument_link_status") == "unresolved_no_match"
                        and choice.get("instrument_id") is None
                    )
                    or (
                        choice.get("instrument_link_status") == "linked"
                        and choice.get("instrument_id") == target
                    )
                )
                or not _source_allows_payout(session, view, instrument.isin)
                or (occurrence is not None and owners(session, [occurrence]))
                or effective_payout_match(
                    session, view, row, choice, resolver, allow_multiple=True, check_choice=False
                )
                is not None
            ):
                valid = False
                break
        if valid:
            result.update((ref, instrument.isin) for _, _, _, _, ref in members)
    return result


def canonical_payout_groups(session, views, resolver=None):
    """Exact accepted cohorts, shared by account and instrument projections.

    Descriptions are not identity. Every selected cohort member must independently
    pass the existing current Money proof and saved-choice checks. Two occurrences
    in one original never collapse through this cross-original rule.
    """
    from collections import defaultdict

    from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
    from hermes_finance.services.source_money_classifications import source_reference

    groups = defaultdict(list)
    for view in views:
        saved = {s["source_reference"]: s for s in view["money_classifications"]}
        source = bound_import(session, view)
        if source is None:
            continue
        if resolver is None:
            resolver = MoneyInstrumentResolver(session)
        for row in view["document"].get("money", []):
            ref = source_reference(view["id"], row)
            choice = saved.get(ref)
            if choice is None:
                continue
            match = effective_payout_match(
                session, view, row, choice, resolver, allow_multiple=True
            )
            if match:
                groups[match[:4]].append(
                    (view, row, ref, (source.id, "money", row["ordinal"], digest(row)), match[4])
                )
    result = {}
    for identity, members in groups.items():
        keys = {m[3] for m in members}
        ids = {m[0]["id"] for m in members}
        day = members[0][1]["date"]
        covering = {v["id"] for v in views if v["covered_from"] <= day <= v["covered_to"]}
        if (
            len(ids) != len(members)
            or len(keys) != len(members)
            or covering != ids
            or any(m[4] != keys for m in members)
            or len({(m[1]["date"], m[1]["source_account"]) for m in members}) != 1
        ):
            continue
        for _, _, ref, _, _ in members:
            result[ref] = identity
    return result


def effective_overlapping_payout(
    session, views, view, row, saved, resolver, *, canonical_matches=None
):
    """Project one current receipt only across uniquely identical source rows."""
    from hermes_finance.services.source_money_classifications import source_reference

    matches = (
        canonical_matches
        if canonical_matches is not None
        else canonical_payout_groups(session, views, resolver)
    )
    exact = matches.get(source_reference(view["id"], row))
    if exact is not None:
        return exact[0]
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


def historical_payout_evidence(
    session, source_account, selected, native_scope, retained_proofs=None
):
    """Reuse current original-bound components, never interior endpoint values.

    Values are exact (intake, ordinal) identities. None is a conflict tombstone,
    not an absent proof. No link/classification/financial row is persisted.
    """
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.broker_statement_provisional import _minor
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.statement_import.money import normalize_currency

    if native_scope is None or len(native_scope) != 1:
        return {}
    views = {view["document_sha256"]: view for _, view, error in selected if view and not error}
    unavailable = [(o.covered_from, o.covered_to) for o, v, error in selected if error or not v]
    analyses = {}
    reports = proofs.read_reports(
        session, source_account=source_account, analyses=analyses, include_xirr=False
    )
    current = {r["proof_id"] for r in reports if r["status"] == "current"}
    if retained_proofs is not None:
        for proof_id in current:
            for isin, analysis in analyses.get(proof_id, {}).items():
                retained_proofs.setdefault(isin, []).append(analysis)
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
                    or event.event_date is None
                    or any(start <= event.event_date <= end for start, end in unavailable)
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


def effective_historical_payout(
    session, views, view, row, saved, resolver, evidence, *, allow_multiple=False
):
    """One exact source group may reuse an agreed current historical payout.

    Return (ISIN, conflict). A failed proof never manufactures Money authority.
    """
    from hermes_finance.services.source_money_classifications import source_reference

    if not evidence or saved.get("classification") not in {"coupon", "dividend"}:
        return None, False
    covering = [v for v in (views or [view]) if v["covered_from"] <= row["date"] <= v["covered_to"]]
    signature = {k: v for k, v in row.items() if k not in {"ordinal", "last_update"}}
    matches, group_refs = [], []
    multiplicity = sum(
        {k: v for k, v in raw.items() if k not in {"ordinal", "last_update"}} == signature
        for raw in view["document"].get("money", [])
    )
    for candidate in covering:
        rows = [
            r
            for r in candidate["document"].get("money", [])
            if {k: v for k, v in r.items() if k not in {"ordinal", "last_update"}} == signature
        ]
        if not rows or len(rows) != (multiplicity if allow_multiple else 1):
            return None, False
        refs = []
        for raw in rows:
            ref = source_reference(candidate["id"], raw)
            choices = [
                c for c in candidate["money_classifications"] if c["source_reference"] == ref
            ]
            if len(choices) != 1:
                return None, False
            refs.append(ref)
            matches.append((candidate, raw, choices[0], ref))
        group_refs.append(refs)
    # One attested row cannot attest another identical occurrence. Require a
    # whole original's group and equal multiplicity in every covering original.
    if multiplicity > 1 and not any(all(ref in evidence for ref in refs) for refs in group_refs):
        return None, False
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
