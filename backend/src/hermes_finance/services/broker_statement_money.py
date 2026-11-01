"""Typed source evidence adapter into the existing Money/ICF/trade writers."""

import json
from calendar import monthrange
from datetime import date

from pydantic import ValidationError

from hermes_finance.domain.broker_money import (
    AccountFeeDecision,
    BrokerBonusDecision,
    BrokerBonusReview,
    MoneyDecision,
    MoneyIntentV3,
)
from hermes_finance.persistence import (
    Account,
    BrokerMonthApply,
    ExecutedTrade,
    Instrument,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_money as money
from hermes_finance.services import broker_months, executed_trades
from hermes_finance.services.broker_money_ownership import conflicts
from hermes_finance.statement_import.broker_intake_evidence import read_intake_evidence
from hermes_finance.statement_import.mybroker import MyBrokerError, digest

CONTRACT = "broker-statement-money-evidence-v1"
BOND = "bond_source_caption_v1"


def reviewed_bonus(session, source, inventory, sources, review, raw):
    """No automatic recognition: confirm only an explicitly selected native row."""
    from hermes_finance.services.mybroker_money_candidates import _narratives
    from hermes_finance.services.source_money_classifications import _is_promo_gift

    if not isinstance(review, BrokerBonusReview):
        review = BrokerBonusReview.model_validate(review)
    if review.seed.import_id != source.id or not review.confirmed_broker_bonus:
        raise MyBrokerError("exact_confirmed_broker_bonus_required")
    reasons = set()
    observation, refs = money._cohort(inventory, review.seed, sources, reasons)
    if reasons or observation is None or len(refs) != 1:
        raise MyBrokerError("broker_bonus_complete_occurrence_required")
    row = observation["row"]
    if (
        review.row_fingerprint != digest(row)
        or row["kind"] != "unsupported"
        or observation["trade_identity"] is not None
        or row["currency"] != "RUB"
        or observation["amount_minor"] is None
        or observation["amount_minor"] <= 0
        or not str(source.covered_from) <= row["date"] <= str(source.covered_to)
    ):
        raise MyBrokerError("broker_bonus_source_facts_invalid")
    # Reuse the existing narrow promo shape as a refusal guard. It grants no
    # bonus authority by itself and never changes provisional classifications.
    operation, narrative, _ = list(_narratives(raw))[row["ordinal"]]
    if digest([operation, narrative]) != observation["narrative_digest"] or not _is_promo_gift(
        operation, narrative
    ):
        raise MyBrokerError("broker_bonus_native_shape_required")
    target_id = f"{source.id}:{row['ordinal']}"
    if conflicts(session, refs, "broker_bonus", target_id):
        raise MyBrokerError("broker_bonus_occurrence_already_owned")
    model = BrokerBonusDecision(**review.model_dump())
    return model, {
        "decision": model.model_dump(mode="json"),
        "target_id": target_id,
        "occurrences": refs,
    }


def base_blockers(session, base, *, require_draft):
    """Keep ordinary Money's base/account guards on the compiled path too."""
    from hermes_finance.services import broker_month_journal as journal

    if base is None or journal.kind(base) != journal.SOURCE:
        return ["existing_source_draft_required"]
    month = session.get(ReportingMonth, base.reporting_month_id, populate_existing=True)
    account = session.get(Account, base.account_id, populate_existing=True)
    source = session.get(MyBrokerImport, base.import_id, populate_existing=True)
    blockers = set()
    if (
        account is None
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        blockers.add("active_brokerage_account_required")
    if month is None or (require_draft and month.status != "draft"):
        blockers.add("reporting_month_closed")
    if month is not None:
        if (month.period_start, month.period_end, month.snapshot_date) != (
            date(month.year, month.month, 1),
            date(month.year, month.month, monthrange(month.year, month.month)[1]),
            month.period_end,
        ):
            blockers.add("source_month_range_mismatch")
        if source is None or (source.covered_from, source.covered_to) != (
            month.period_start,
            month.period_end,
        ):
            blockers.add("source_month_range_mismatch")
        if broker_months._projection(session, base) != journal.payload(base)["projection_digest"]:
            blockers.add("source_projection_changed")
    if (
        source is None
        or digest([source.normalized_json, source.mappings_json, source.parser_version])
        != journal.payload(base)["source_digest"]
    ):
        blockers.add("source_authority_changed")
    return sorted(blockers)


def _ref(source, row):
    return {
        "import_id": source.id,
        "section": "money",
        "ordinal": row["ordinal"],
        "row_fingerprint": digest(row),
    }


def plan_statement_money(session, base, original, *, payouts, broker_bonuses=()):
    """Compile only the supplied typed evidence, never client amounts or claims.

    Payout identity evidence comes from the existing XML/PDF exact-group reader.
    Unhandled source rows remain Close blockers; this adapter cannot zero them.
    """
    if payouts:
        raise MyBrokerError("statement_evidence_cannot_change_payouts")
    if reasons := base_blockers(session, base, require_draft=True):
        raise MyBrokerError(",".join(reasons))
    source = session.get(MyBrokerImport, base.import_id)
    document = json.loads(source.normalized_json)
    filename, raw = original
    typed = read_intake_evidence(raw, filename, source=document)
    if typed["issues"]:
        raise MyBrokerError("statement_trade_evidence_review_required")
    intent = MoneyIntentV3(
        base_request_id=base.request_id,
        reporting_month_id=base.reporting_month_id,
        account_id=base.account_id,
    )
    inventory, sources, blockers = money._union(session, intent, [original])
    if blockers or len(sources) != 1:
        raise MyBrokerError("statement_overlapping_originals_review_required")
    decisions, groups, models = [], [], []
    native_context = executed_trades._context(session)
    by_identity = {t.source_identity: t for t in broker_months._rows(session, ExecutedTrade)}
    for cohort in typed["nkd_cohorts"]:
        group = {
            **cohort,
            "import_id": source.id,
            "group_id": digest([source.id, cohort["cohort_digest"]]),
            "occurrences": [
                {**r, "import_id": source.id, "section": "money"} for r in cohort["occurrences"]
            ],
        }
        if conflicts(session, group["occurrences"], "trade_group", group["group_id"]):
            raise MyBrokerError("statement_nkd_occurrence_already_owned")
        groups.append(group)
        for identity in cohort["trade_identities"]:
            trade = by_identity.get(identity)
            if trade is None or trade.account_id != base.account_id:
                raise MyBrokerError("statement_native_trade_changed")
            candidate = executed_trades._candidate(session, native_context, identity, cash_proof={})
            evidence = candidate["evidence"]
            instrument = session.get(Instrument, trade.instrument_id)
            if (
                not instrument
                or instrument.instrument_type != "bond"
                or instrument.currency != "RUB"
            ):
                raise MyBrokerError("statement_rub_bond_required")
            nkd = cohort["signed_nkd_minor"]
            proof = {
                "proof_variant": BOND,
                "source_identity": identity,
                "native_ids": candidate["ids"],
                "cohort": group,
                "source_sha256": source.document_sha256,
                "claims": {"native_total_basis": "includes_paid_nkd"},
                "nkd_leg": {
                    "role": "paid_nkd",
                    "source_account": trade.source_account,
                    "effective_date": cohort["date"],
                    "currency": "RUB",
                    "amount_minor": abs(nkd),
                    "direction": "debit" if nkd < 0 else "credit",
                    "source_amount": str(nkd // 100)
                    if nkd % 100 == 0
                    else str(__import__("decimal").Decimal(nkd) / 100),
                    "occurrences": [],
                    "observed_multiplicity": 1,
                    "equivalent_cohort": group["group_id"],
                },
            }
            candidate = executed_trades._candidate(
                session, native_context, identity, cash_proof=proof
            )
            if candidate["conflicts"] or broker_months._bookkeeping_trade_blockers(candidate):
                raise MyBrokerError("statement_trade_cash_control_failed")
            refs = [
                {
                    "import_id": o["import_id"],
                    "section": "money",
                    "ordinal": o["ordinal"],
                    "row_fingerprint": o["source_fingerprint"],
                }
                for leg in evidence["cash_legs"]
                for o in leg["occurrences"]
            ]
            if conflicts(session, refs, "trade", trade.id):
                raise MyBrokerError("statement_trade_occurrence_already_owned")
            model = MoneyDecision(
                role="trade",
                seed={k: refs[0][k] for k in ("import_id", "section", "ordinal")},
                trade_id=trade.id,
                expected_trade_revision=candidate["revision"],
            )
            models.append(model)
            decisions.append(
                {
                    "decision": model.model_dump(mode="json"),
                    "target_id": trade.id,
                    "candidate": candidate,
                    "occurrences": refs,
                }
            )
    for fee in typed["account_fees"]:
        row = next(r for r in document["money"] if r["ordinal"] == fee["ordinal"])
        ref = _ref(source, row)
        target_id = f"{source.id}:{row['ordinal']}"
        if conflicts(session, [ref], "account_fee", target_id):
            raise MyBrokerError("statement_account_fee_already_owned")
        model = AccountFeeDecision(
            role="account_fee", seed={k: ref[k] for k in ("import_id", "section", "ordinal")}
        )
        models.append(model)
        decisions.append(
            {
                "decision": model.model_dump(mode="json"),
                "target_id": target_id,
                "occurrences": [ref],
            }
        )
    if len(broker_bonuses) > 1:
        raise MyBrokerError("one_broker_bonus_review_per_source_required")
    for review in broker_bonuses:
        model, decision = reviewed_bonus(session, source, inventory, sources, review, raw)
        models.append(model)
        decisions.append(decision)
    intent = intent.model_copy(update={"money_decisions": models})
    statement = {
        "contract_version": CONTRACT,
        "source_sha256": source.document_sha256,
        "typed_evidence": typed,
        "instruments": [
            money.material(session.get(Instrument, i))
            for i in sorted(
                {
                    t.instrument_id
                    for t in by_identity.values()
                    if t.source_identity
                    in {
                        identity for c in typed["nkd_cohorts"] for identity in c["trade_identities"]
                    }
                }
            )
        ],
    }
    plan = {
        "sources": sources,
        "decisions": decisions,
        "statement_evidence": statement,
        "statement_groups": groups,
        "can_apply": True,
        "dependency_digest": money._dependencies(session),
    }
    from hermes_finance.services.actual_payouts import _physical

    plan["physical_incarnation"] = _physical(session)
    plan["confirmation_digest"] = digest([intent.model_dump(mode="json"), plan])
    return intent, plan


def statement_proof_blockers(session, receipt, proof):
    from hermes_finance.database import snapshot_read_result

    return snapshot_read_result(
        session,
        "broker_statement_proof_blockers",
        (receipt.request_id, digest(proof)),
        lambda: _statement_proof_blockers(session, receipt, proof),
    )


def _statement_proof_blockers(session, receipt, proof):
    base = session.get(BrokerMonthApply, proof["base_request_id"], populate_existing=True)
    if reasons := base_blockers(session, base, require_draft=False):
        return reasons
    if any(t.get("role") not in {"trade", "account_fee", "broker_bonus"} for t in proof["targets"]):
        return ["statement_money_target_role_invalid"]
    statement = proof.get("statement_evidence", {})
    if statement.get("contract_version") != CONTRACT:
        return ["statement_money_evidence_invalid"]
    source = session.get(MyBrokerImport, receipt.import_id, populate_existing=True)
    if not source or statement.get("source_sha256") != source.document_sha256:
        return ["statement_money_source_changed"]
    for target in proof["targets"]:
        if target["role"] != "broker_bonus":
            continue
        reviews = [
            d
            for d in proof["decisions"]
            if d["role"] == "broker_bonus"
            and f"{d['seed']['import_id']}:{d['seed']['ordinal']}" == target["target_id"]
        ]
        if (
            len(reviews) != 1
            or not reviews[0]["confirmed_broker_bonus"]
            or reviews[0]["row_fingerprint"] != digest(target["facts"])
        ):
            return ["broker_bonus_review_changed"]
        try:
            review = BrokerBonusDecision.model_validate(reviews[0])
        except (ValidationError, TypeError):
            return ["broker_bonus_review_changed"]
        bonus_refs = [
            o
            for o in proof["occurrences"]
            if o["role"] == "broker_bonus" and o["target_id"] == target["target_id"]
        ]
        if (
            len(bonus_refs) != 1
            or review.seed.import_id != source.id
            or {k: bonus_refs[0][k] for k in ("import_id", "section", "ordinal")}
            != review.seed.model_dump()
            or bonus_refs[0]["row_fingerprint"] != review.row_fingerprint
        ):
            return ["broker_bonus_occurrence_changed"]
    for old in statement.get("instruments", []):
        if money.material(session.get(Instrument, int(old["id"]), populate_existing=True)) != old:
            return ["statement_money_instrument_changed"]
    for group in proof.get("statement_groups", []):
        expected = [
            c
            for c in statement["typed_evidence"]["nkd_cohorts"]
            if c["cohort_digest"] == group["cohort_digest"]
        ]
        if len(expected) != 1 or group["group_id"] != digest([source.id, group["cohort_digest"]]):
            return ["statement_nkd_group_changed"]
        document = json.loads(source.normalized_json)
        rows = {r["ordinal"]: r for r in document["money"]}
        if any(
            ref["import_id"] != source.id
            or ref["ordinal"] not in rows
            or digest(rows[ref["ordinal"]]) != ref["row_fingerprint"]
            for ref in group["occurrences"]
        ):
            return ["statement_nkd_occurrence_changed"]
        targets = [
            t
            for t in proof["targets"]
            if t["role"] == "trade"
            and t.get("cash_proof", {}).get("cohort", {}).get("group_id") == group["group_id"]
        ]
        if sorted(t["cash_proof"]["source_identity"] for t in targets) != group["trade_identities"]:
            return ["statement_nkd_group_incomplete"]
        if any(money._target(session, "trade", t["target_id"]) != t for t in targets):
            return ["statement_nkd_trade_changed"]
    return []


def effective_statement_occurrence(session, source_id, row):
    latest = money.latest_proofs(session)
    for receipt, proof in money.receipts(session):
        if proof["contract_version"] != money.CONTRACT_V3 or proof["operation"] == "retire":
            continue
        for target in proof["targets"]:
            if (
                target["role"] not in {"account_fee", "broker_bonus"}
                or target["target_id"] != f"{source_id}:{row['ordinal']}"
            ):
                continue
            entry = latest.get(money.target_key(target))
            if (
                entry
                and entry[0].request_id == receipt.request_id
                and not money.proof_blockers(session, *entry)
            ):
                return True
        for group in proof.get("statement_groups", []):
            if not any(
                r["import_id"] == source_id
                and r["ordinal"] == row["ordinal"]
                and r["row_fingerprint"] == digest(row)
                for r in group["occurrences"]
            ):
                continue
            entries = [
                latest.get(("trade", t["target_id"]))
                for t in proof["targets"]
                if t["role"] == "trade"
                and t["cash_proof"]["cohort"]["group_id"] == group["group_id"]
            ]
            if entries and all(
                e
                and e[0].request_id == receipt.request_id
                and not money.proof_blockers(session, *e)
                for e in entries
            ):
                return True
    return False
