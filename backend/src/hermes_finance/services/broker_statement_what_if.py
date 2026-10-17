"""Read-only composition of existing authority readers; no copied authority resolver."""

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from xml.etree import ElementTree as ET

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.broker_statement_what_if import (
    METHOD,
    VERSION,
    AssumptionRequirement,
    StatementWhatIfContext,
    WhatIfFlow,
    WhatIfObserved,
    evaluate_context,
)
from hermes_finance.persistence import MyBrokerImport
from hermes_finance.services import broker_money_ownership, source_cash_coverage
from hermes_finance.services.broker_statement_return import read_statement_return
from hermes_finance.services.mybroker_money_candidates import read_money_candidates
from hermes_finance.statement_import.mybroker import MyBrokerError, digest
from hermes_finance.statement_import.mybroker_metadata import parse_section_metadata

# These literal diagnostic codes are conditional on complete, independently
# inspected inventory below. Every other code, including future codes, is hard.
SCOPED_REASONS = {
    "account_crossing_coverage_unproved": "remaining_crossings",
    "historical_membership_not_continuously_included": "native_basis",
    "money_semantics_unsupported": "money_inventory",
    "money_disposition_unresolved": "money_inventory",
    "commission_basis_unresolved": "money_basis",
    "commission_missing": "money_basis",
    "material_account_exposure_unassessed": "residual",
    "4_Transfers_unsupported": "residual",
    "5_UFSR_unsupported": "residual",
}
MONEY_DIAGNOSTICS = frozenset(
    {
        "summary_proof_unavailable",
        "economic_identity_unproven",
        "money_semantics_unsupported",
        "owner_crossing_unproven",
        "portfolio_externality_unproven",
        "instrument_link_unproven",
        "trade_link_unproven",
        "paid_nkd_basis_unproven",
        "commission_basis_unresolved",
        "commission_missing",
        "4_Transfers_unsupported",
        "5_UFSR_unsupported",
    }
)
H2_PATTERN_DIAGNOSTICS = frozenset({"source_pattern_unproven", "candidate_direction_invalid"})
LIMITATIONS = (
    "Условная модель выбранного счёта, не фактическая доходность и не доходность портфеля.",
    "Условный результат после учёта выбранных внешних движений",
    "Полнота фактических пересечений и экономический охват периода не подтверждаются сценарием.",
    "Нативная дата проводки не доказывает дату списания банком или внешность для портфеля.",
    "НКД, налог и комиссии не приравниваются к нулю и не добавляются к cash повторно.",
)


class WhatIfStaleError(ValueError):
    pass


def _reference(occurrence):
    return (
        f"money:{occurrence['import_id']}:{occurrence['section']}:"
        f"{occurrence['ordinal']}:{occurrence['row_fingerprint']}"
    )


def _json_money(value, key=""):
    """Retain raw diagnostic structure while preserving exact minor-unit JSON."""
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if k in {
                "signed_amount",
                "signed_source_amount",
                "amount",
                "trade_amount",
                "bank_commission",
                "accrued_interest",
            }:
                result[k + "_kopecks"] = _source_minor(v)
            elif k == "source_subtotals":
                result["source_subtotals_kopecks"] = {
                    name: _source_minor(amount) for name, amount in v.items()
                }
            else:
                result[k] = _json_money(v, k)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_money(v, key) for v in value]
    if isinstance(value, int) and (key.endswith("_kopecks") or key == "amount_minor"):
        return str(value)
    return value


def _source_minor(value):
    if value is None:
        return None
    try:
        with localcontext() as context:
            context.prec = 100
            minor = Decimal(value) * 100
            return (
                str(int(minor))
                if minor.is_finite() and minor == minor.to_integral_value()
                else None
            )
    except (DecimalException, ValueError, TypeError):
        return None


def _empty_channel(original, section):
    """A zero node count alone must not hide attributes/text/comments as empty.

    This checks absence only; nonempty safe patterns still come exclusively from
    the existing metadata parser, and neither supplies economic-period authority.
    """
    root = ET.fromstring(
        original.decode("utf-8-sig"),
        parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)),
    )
    outer = {"4_Transfers": "Trades3", "5_UFSR": "Trades4"}[section]
    wrappers = [
        node for node in root if isinstance(node.tag, str) and node.tag.rsplit("}", 1)[-1] == outer
    ]
    if len(wrappers) != 1:
        return False
    wrapper = wrappers[0]
    if wrapper.tag != f"{{MyBroker}}{outer}" or wrapper.attrib or len(wrapper) != 1:
        return False
    report = wrapper[0]
    return (
        report.tag == "{MyBroker}Report"
        and report.attrib == {"Name": section}
        and not len(report)
        and all(
            not (value or "").strip()
            for value in (wrapper.text, wrapper.tail, report.text, report.tail)
        )
    )


@coherent_read_operation
def read_context(
    session, *, account_id, request_id, original, filename, expected_actual_fingerprint
):
    actual = read_statement_return(
        session, account_id=account_id, request_id=request_id, original=original, filename=filename
    )
    if actual.material_fingerprint != expected_actual_fingerprint:
        raise WhatIfStaleError("what_if_actual_stale")
    source = actual.sources[0]
    hard = set()
    requirements = []
    native_ref = f"source:{source.import_id}:{source.document_sha256}:{actual.material_fingerprint}"

    def require(key, slot, refs, *choices, subject=None):
        requirements.append(
            AssumptionRequirement(
                requirement_id=key,
                subject=subject
                or {
                    "native_basis": "Выбранный счёт и обе EOD оценки",
                    "schedule": "Полный показанный график",
                    "candidate": "Нативное входящее поступление",
                    "remaining_crossings": "Только выбранный счёт и его точный период",
                }.get(key, key),
                slot=slot,
                source_references=tuple(sorted(refs)),
                choices=tuple(choices),
            )
        )

    require("native_basis", "native_basis", [native_ref], "native_totals_continuously")
    try:
        cash = source_cash_coverage.inventory(
            session, account_id, actual.t0, actual.t1, contract=source_cash_coverage.CONTRACT
        )
        cash_error = None
    except (MyBrokerError, DecimalException, ValueError, TypeError, KeyError) as error:
        # The unchanged reader may refuse a corrupt dependency before returning
        # diagnostics. Unavailable is not an invented empty inventory.
        cash, cash_error = None, type(error).__name__
        hard.add("what_if_h2_inventory_invalid")
    money, metadata, ownership = None, None, []
    try:
        money = read_money_candidates(
            session,
            import_id=source.import_id,
            document=original,
            filename=filename,
            account_id=account_id,
        )
        metadata = parse_section_metadata(original, filename)
        ownership = broker_money_ownership.owners(
            session, money.observations and [asdict(o.occurrence) for o in money.observations] or []
        )
    except (MyBrokerError, ValueError, TypeError, KeyError) as error:
        hard.add("what_if_original_inventory_invalid")
        inventory_error = str(error)
    else:
        inventory_error = None
    fixed = tuple(
        WhatIfFlow(
            source_reference=f"h2:{c.event_id}:{c.revision_id}:{c.material_signature}",
            event_date=c.event_date,
            signed_amount_kopecks=str(c.signed_amount_kopecks),
            provenance="accepted_h2",
        )
        for c in actual.crossings
    )
    if len(fixed) > 128:
        hard.add("what_if_crossing_capacity_exceeded")
    fixed_ids = {c.event_id for c in actual.crossings}
    if cash is not None and fixed_ids != set(cash["effective_flow_ids"]):
        hard.add("what_if_fixed_schedule_mismatch")
    optional = []
    dispositions = {
        (d["import_id"], d["section"], d["ordinal"]): d
        for d in (cash["money_dispositions"] if cash else [])
    }
    money_refs = []
    if money:
        if money.overlapping_sources:
            hard.add("what_if_overlapping_source")
        occurrence_reasons = {reason for o in money.observations for reason in o.reasons}
        hard.update(set(money.exceptions) - occurrence_reasons - MONEY_DIAGNOSTICS)
        for observed in money.observations:
            # Narrative discovery is not accepted H2 authority. Keep every raw
            # diagnostic, but resolve only these two pattern gaps behind a
            # compatible effective fixed crossing. Unknown/integrity codes block
            # even an otherwise accepted occurrence.
            hard.update(set(observed.reasons) - MONEY_DIAGNOSTICS - H2_PATTERN_DIAGNOSTICS)
            pattern_gaps = set(observed.reasons) & H2_PATTERN_DIAGNOSTICS
            occurrence = asdict(observed.occurrence)
            ref = _reference(occurrence)
            money_subject = f"{observed.date} · {observed.s1_kind} / {observed.candidate_kind} · {observed.amount_minor} коп."
            money_refs.append(ref)
            key = broker_money_ownership.key(occurrence)
            disposition = dispositions.get(key)
            if (
                not disposition
                or disposition["row_fingerprint"] != occurrence["row_fingerprint"]
                or observed.account_id != account_id
                or observed.currency != "RUB"
                or observed.amount_minor is None
                or not actual.t0.isoformat() < observed.date <= actual.t1.isoformat()
            ):
                hard.add("what_if_money_identity_invalid")
                continue
            owned = [o for o in ownership if tuple(o["key"]) == key]
            targets = {(o["role"], o["target_id"], o["row_fingerprint"]) for o in owned}
            accepted = disposition["disposition"]
            if owned:
                if len(targets) != 1 or any(
                    o["row_fingerprint"] != occurrence["row_fingerprint"] for o in owned
                ):
                    hard.add("what_if_ownership_conflict")
                    continue
                role, target, _ = next(iter(targets))
                compatible = (
                    role == "account_funding"
                    and target in fixed_ids
                    and accepted == "effective_owner_flow"
                    and any(o["flow_id"] == target for o in disposition["owners"])
                    or role == "coupon"
                    and accepted == "accepted_non_owner_coupon"
                    and disposition.get("coupon_target_id") == target
                    or role == "trade"
                    and (
                        accepted == "accepted_non_owner_trade_cash"
                        or accepted == "accepted_non_owner_paid_nkd"
                        and len(owned) == 1
                        and disposition.get("trade_target_id") == target
                    )
                )
                if not compatible:
                    hard.add("what_if_ownership_ineffective_or_incompatible")
                elif role != "account_funding":
                    hard.update(pattern_gaps)
                if compatible and role == "trade":
                    require(
                        ref,
                        "money_basis",
                        [ref],
                        "no_additional_flow_or_adjustment",
                        subject=money_subject,
                    )
                continue
            if accepted in {
                "effective_owner_flow",
                "accepted_non_owner_coupon",
                "accepted_non_owner_paid_nkd",
            }:
                hard.add("what_if_ownership_inventory_mismatch")
                continue
            if accepted == "accepted_non_owner_trade_cash":
                hard.update(pattern_gaps)
                require(
                    ref,
                    "money_basis",
                    [ref],
                    "no_additional_flow_or_adjustment",
                    subject=money_subject,
                )
                continue
            if set(observed.reasons) - MONEY_DIAGNOSTICS:
                hard.add("what_if_money_diagnostic_unmapped")
                if observed.candidate_kind == "unsupported":
                    hard.add("what_if_money_unsupported")
                continue
            if observed.candidate_kind == "account_cash_in_candidate" and observed.amount_minor > 0:
                optional.append(
                    WhatIfFlow(
                        source_reference=ref,
                        event_date=date.fromisoformat(observed.date),
                        signed_amount_kopecks=str(observed.amount_minor),
                        provenance="assumed_native_incoming",
                    )
                )
            elif observed.candidate_kind in {"coupon_paid_candidate", "trade_paid_nkd_candidate"}:
                require(
                    ref,
                    "money_basis",
                    [ref],
                    "no_additional_flow_or_adjustment",
                    subject=money_subject,
                )
            elif (
                observed.s1_kind in {"settlement", "commission"}
                and observed.trade_identity
                and disposition.get("linked_trade")
                and disposition["linked_trade"]["state"] == "settled"
                and not set(disposition["linked_trade"]["blockers"])
                - {"commission_missing", "commission_basis_unresolved"}
            ):
                require(
                    ref,
                    "money_basis",
                    [ref],
                    "no_additional_flow_or_adjustment",
                    subject=money_subject,
                )
            else:
                hard.add("what_if_money_unsupported")
    if (
        len(optional) > 1
        or money
        and sum(
            o.candidate_kind == "account_cash_in_candidate"
            and not any(
                tuple(owner["key"]) == broker_money_ownership.key(o.occurrence)
                for owner in ownership
            )
            for o in money.observations
        )
        > 1
    ):
        hard.add("what_if_candidate_capacity_exceeded")
    candidate = optional[0] if len(optional) == 1 else None
    if candidate:
        require(
            "candidate",
            "schedule",
            [candidate.source_reference],
            "include_as_account_inflow",
            "exclude_from_external_schedule",
        )
    require(
        "schedule",
        "schedule",
        [f.source_reference for f in fixed] + [f.source_reference for f in optional],
        "use_displayed_schedule",
    )
    if actual.cash_coverage_state != "complete":
        require(
            "remaining_crossings",
            "remaining_crossings",
            [native_ref, *money_refs, *(f.source_reference for f in fixed)],
            "no_other_account_crossings",
        )
    residual_ok = metadata is not None
    if metadata:
        for channel in metadata["sections"]:
            # An absent/empty observed channel is explicitly modelled, not inferred
            # to be accepted economic-period coverage. Nonempty unsafe trees block.
            safe = channel["status"] == "READY_SAFE_STRUCTURE"
            empty = channel["raw_inventory"] == 0 and _empty_channel(original, channel["section"])
            if not (safe or empty):
                residual_ok = False
                hard.add("what_if_unmodelled_exposure")
            else:
                ref = f"section:{source.import_id}:{channel['section']}:{digest(channel)}"
                require(
                    ref,
                    "residual",
                    [ref],
                    "no_additional_channel_effect",
                    subject=f"{channel['section']} · {channel['pattern'] or 'empty_observed_inventory'} · охват периода неизвестен",
                )
    codes = set(actual.reason_codes) | set(cash["blockers"] if cash else [])
    if metadata:
        codes.update(metadata["source_warnings"])
    for code in codes:
        slot = SCOPED_REASONS.get(code)
        if slot is None:
            hard.add(code)
        elif slot == "residual" and not residual_ok:
            hard.add(code)
        elif slot == "money_basis" and not any(r.slot == "money_basis" for r in requirements):
            hard.add(code)
        elif slot == "money_inventory" and money is None:
            hard.add(code)
    # Even safely parsed residual channels cannot dismiss REPO/pending inventory.
    if money and (
        money.section_inventory.get("2_Unexecuted", 0) or money.section_inventory.get("repo", 0)
    ):
        hard.add("what_if_unmodelled_exposure")
    # Use the full H2 source dependency inventory to find parsed REPO/pending facts.
    try:
        stored = json.loads(session.get(MyBrokerImport, source.import_id).normalized_json)
        if any(t["repo_observed"] or t["section"] == "pending" for t in stored["trades"]):
            hard.add("what_if_unmodelled_exposure")
    except (ValueError, TypeError, KeyError):
        # S3 can itself return unavailable for a corrupt envelope. Do not let a
        # second diagnostic read escape that fail-closed context or its no-store API.
        hard.add("what_if_source_inventory_invalid")
    raw_inventory = {
        "money": asdict(money) if money else None,
        "h2": cash,
        "h2_inventory_error": cash_error,
        "metadata": metadata,
        "ownership": sorted(ownership, key=digest),
        "inventory_error": inventory_error,
    }
    inventory = _json_money(raw_inventory)
    inventory["raw_dependency_fingerprint"] = digest(raw_inventory)
    # Preserve only independently verified endpoint facts. The unchanged actual
    # envelope is still included verbatim as diagnostics, never relabelled observed.
    verified = not (set(actual.reason_codes) - set(SCOPED_REASONS))
    v0, v1 = actual.opening.total_value_kopecks, actual.closing.total_value_kopecks
    observed = WhatIfObserved(
        opening=actual.opening if verified else None,
        closing=actual.closing if verified else None,
        capital_delta_kopecks=str(v1 - v0)
        if verified and v0 is not None and v1 is not None
        else None,
    )
    payload = dict(
        account_id=account_id,
        request_id=request_id,
        t0=actual.t0,
        t1=actual.t1,
        observed=observed,
        actual_result=actual,
        diagnostic_inventory=inventory,
        fixed_schedule=fixed,
        optional_candidate=candidate,
        required_assumptions=tuple(requirements),
        hard_blockers=tuple(sorted(hard)),
        limitations=(*LIMITATIONS, *actual.warnings),
    )
    provisional = StatementWhatIfContext(**payload, context_fingerprint="0" * 64)
    fingerprint = digest(
        {
            "method": METHOD,
            "version": VERSION,
            "inventory_contract": source_cash_coverage.CONTRACT,
            "context": provisional.model_dump(mode="json", exclude={"context_fingerprint"}),
        }
    )
    return provisional.model_copy(update={"context_fingerprint": fingerprint})


@coherent_read_operation
def evaluate(
    session,
    *,
    assumptions,
    expected_context_fingerprint,
    expected_result_fingerprint=None,
    **source,
):
    context = read_context(session, **source)
    if context.context_fingerprint != expected_context_fingerprint:
        raise WhatIfStaleError("what_if_context_stale")
    # Ordering selections is immaterial; references within each choice remain exact.
    assumptions = assumptions.model_copy(
        update={"selections": tuple(sorted(assumptions.selections, key=lambda s: s.requirement_id))}
    )
    result = evaluate_context(context, assumptions)
    if (
        expected_result_fingerprint is not None
        and result.result_fingerprint != expected_result_fingerprint
    ):
        raise WhatIfStaleError("what_if_result_stale")
    return result
