"""Typed reviewed posted BUY cash, never a cost, coupon or endpoint projection."""

from collections import Counter
from decimal import Decimal, localcontext

from sqlalchemy import select

from hermes_finance.domain.broker_money import StockFeeClaims, TradeCashClaims
from hermes_finance.persistence import ExecutedTrade, Instrument
from hermes_finance.services.broker_money_ownership import conflicts, key
from hermes_finance.statement_import.mybroker import digest


def exact_minor(value):
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 100
        amount = Decimal(value) * 100
        if amount != amount.to_integral_value() or not -(2**63) <= amount <= 2**63 - 1:
            return None
        return int(amount)


def effective_proof(session, identity):
    # Deliberately no canonical reader here: proof revalidation reads frozen
    # target revisions, avoiding a candidate -> receipt -> candidate cycle.
    from hermes_finance.services.broker_money import latest_proofs, proof_blockers

    trade = session.scalar(select(ExecutedTrade).where(ExecutedTrade.source_identity == identity))
    if trade is None:
        return None
    entry = latest_proofs(session).get(("trade", trade.id))
    if entry is None or proof_blockers(session, *entry):
        return None
    return entry[2]["cash_proof"]


STOCK_FEE = "stock_buy_separate_fee_v1"


def is_stock_proof(proof):
    return bool(proof and proof.get("proof_variant") == STOCK_FEE)


def stock_cash_reasons(source, groups, proof):
    from pydantic import ValidationError

    try:
        claims = StockFeeClaims.model_validate(proof["claims"])
    except (ValidationError, KeyError):
        return ["stock_fee_specific_proof_required"]
    if "nkd_leg" in proof or groups.get("paid_nkd"):
        return ["stock_paid_nkd_unsupported"]
    if (
        proof.get("native_ids") != source["ids"]
        or proof.get("source_identity") != source["identity"]
    ):
        return ["stock_fee_native_identity_conflict"]
    if not all(
        (
            claims.exact_row_settled_buy_link,
            claims.complete_occurrence_set_is_one_event,
            claims.fee_separately_charged,
            claims.native_total_basis_independently_proved,
        )
    ):
        return ["stock_fee_independent_basis_required"]
    if source["state"] != "settled" or Decimal(source["core"]["quantity"]) <= 0:
        return ["settled_stock_buy_required"]
    accrued = source["accrued_interest"]
    if accrued is not None and Decimal(accrued) != 0:
        return ["stock_accrued_interest_unsupported"]
    legs = [groups.get(role, []) for role in ("settlement", "commission")]
    if any(len(leg) != 1 for leg in legs):
        return ["trade_cash_missing_or_ambiguous"]
    rows = [leg[0] for leg in legs]
    values = [exact_minor(row["amount"]) for row in rows]
    native = [exact_minor(source["core"]["trade_amount"]), exact_minor(source["bank_commission"])]
    if any(v is None for v in values + native):
        return ["trade_cash_exact_kopecks_required"]
    s, f = values
    t, b = native
    if s >= 0 or f >= 0 or t <= 0 or b <= 0:
        return ["negative_posted_cash_nonzero_native_required"]
    if source["core"]["currency"] != "RUB" or not source["depo_settlement_date"]:
        return ["settled_rub_cash_required"]
    if any(row["currency"] != "RUB" or row["date"] != source["settlement_date"] for row in rows):
        return ["trade_cash_date_currency_conflict"]
    if -s != t or -f != b:
        return ["stock_native_total_fee_control_mismatch"]
    if -(s + f) > 2**63 - 1:
        return ["trade_cash_amount_overflow"]
    if proof.get("signed_minor") != {
        "settlement": str(s),
        "commission": str(f),
        "native_total": str(t),
        "native_fee": str(b),
    }:
        return ["trade_cash_material_changed"]
    if source["repo_observed"]:
        return ["repo_semantics_unsupported"]
    return []


def cash_reasons(source, groups, proof):
    """Equations check an independently reviewed basis; they never select it."""
    if not proof:
        return ["paid_nkd_basis_unresolved"]
    if is_stock_proof(proof):
        return stock_cash_reasons(source, groups, proof)
    if "proof_variant" in proof or not isinstance(proof.get("claims"), dict):
        return ["trade_cash_proof_variant_unsupported"]
    claims = proof["claims"]
    if not all(
        claims.get(k) is True
        for k in (
            "exact_row_settled_buy_link",
            "complete_occurrence_set_is_one_event",
            "nkd_separately_posted",
            "fee_separately_charged",
            "native_total_basis_independently_proved",
        )
    ):
        return ["trade_cash_specific_proof_required"]
    if source["state"] != "settled" or Decimal(source["core"]["quantity"]) <= 0:
        return ["settled_bond_buy_required"]
    legs = [groups.get(role, []) for role in ("settlement", "paid_nkd", "commission")]
    if any(len(leg) != 1 for leg in legs):
        return ["trade_cash_missing_or_ambiguous"]
    rows = [leg[0] for leg in legs]
    values = [exact_minor(row["amount"]) for row in rows]
    native = [
        exact_minor(source["core"]["trade_amount"]),
        exact_minor(source["accrued_interest"]),
        exact_minor(source["bank_commission"]),
    ]
    if any(v is None for v in values + native):
        return ["trade_cash_exact_kopecks_required"]
    s, n, f = values
    t, nkd, fee = native
    if any(v >= 0 for v in values) or t <= 0 or nkd <= 0 or fee <= 0:
        return ["negative_posted_cash_nonzero_native_required"]
    if any(row["currency"] != "RUB" or row["date"] != source["settlement_date"] for row in rows):
        return ["trade_cash_date_currency_conflict"]
    if source["core"]["currency"] != "RUB" or not source["depo_settlement_date"]:
        return ["settled_rub_cash_required"]
    if -n != nkd or -f != fee:
        return ["native_nkd_fee_amount_conflict"]
    if -(s + n + f) > 2**63 - 1:
        return ["trade_cash_amount_overflow"]
    basis = claims["native_total_basis"]
    control = -(s + n) if basis == "includes_paid_nkd" else -s
    if control != t:
        return ["native_total_basis_control_mismatch"]
    if proof["signed_minor"] != {
        "settlement": str(s),
        "paid_nkd": str(n),
        "commission": str(f),
        "native_total": str(t),
    }:
        return ["trade_cash_material_changed"]
    return []


def plan_trade(session, intent, decision, observation, occurrences, inventory, context, reasons):
    from hermes_finance.services import executed_trades as trades
    from hermes_finance.services.broker_money import latest_proofs, material

    trade = session.get(ExecutedTrade, decision.trade_id) if decision.trade_id else None
    result = {"target_id": decision.trade_id, "action": "revise", "cash_proof": None}
    if trade is None or trade.account_id != intent.account_id:
        reasons.add("exact_settled_trade_required")
        return result
    instrument = session.get(Instrument, trade.instrument_id)
    stock = observation["s1_kind"] == "commission"
    claims = decision.trade_claims
    if claims is not None and not isinstance(claims, StockFeeClaims if stock else TradeCashClaims):
        reasons.add("trade_cash_proof_variant_unsupported")
    required_type = "stock" if stock else "bond"
    if (
        instrument is None
        or instrument.instrument_type != required_type
        or instrument.currency != "RUB"
    ):
        reasons.add(f"exact_rub_{required_type}_link_required")
    candidate = trades._candidate(
        session, trades._context(session), trade.source_identity, cash_proof={}
    )
    if len(candidate["ids"]) != 2:
        reasons.add("exact_ordered_native_ids_required")
    reasons.update(candidate["conflicts"])
    if decision.expected_trade_revision != candidate["revision"]:
        reasons.add("trade_revision_stale")
    previous = latest_proofs(session).get(("trade", trade.id))
    if previous and previous[1]["operation"] == "retire" and decision.operation != "reaffirm":
        reasons.add("reviewed_reaffirmation_required")
    prior_keys = {
        key(o)
        for o in trades._rows(session, trades.ExecutedTradeOccurrence)
        if o.trade_id == trade.id and o.section == "money"
    }
    evidence = candidate["evidence"]
    reasons.update(evidence["readiness"]["unsupported"])
    if observation["source_account"] != trade.source_account:
        reasons.add("trade_cash_source_account_conflict")
    if stock:
        if observation["trade_identity"] != trade.source_identity:
            reasons.add("stock_fee_native_identity_conflict")
        if any(
            o["source_account"] == trade.source_account
            and (
                o["row"].get("primary_id") == candidate["ids"][0]
                or (
                    o["candidate_kind"] == "trade_paid_nkd_candidate"
                    and o["description"] == f"НКД по сделке {candidate['ids'][0]}"
                )
            )
            and o["s1_kind"] not in ("settlement", "commission")
            for o in inventory
        ):
            reasons.add("stock_unexpected_linked_money")
    cash = [leg for leg in evidence["cash_legs"] if leg["role"] in ("settlement", "commission")]
    refs = {} if stock else {"paid_nkd": occurrences}
    groups = (
        {}
        if stock
        else {
            "paid_nkd": [
                {
                    "amount": observation["signed_amount"],
                    "date": observation["date"],
                    "currency": observation["currency"],
                }
            ]
        }
    )
    for role in ("settlement", "commission"):
        selected = [leg for leg in cash if leg["role"] == role]
        groups[role] = [
            {
                "amount": leg["source_amount"],
                "date": leg["effective_date"],
                "currency": leg["currency"],
            }
            for leg in selected
        ]
        refs[role] = [
            {
                "import_id": p["import_id"],
                "section": "money",
                "ordinal": p["ordinal"],
                "row_fingerprint": p["source_fingerprint"],
            }
            for leg in selected
            for p in leg["occurrences"]
        ]
        if any(leg["observed_multiplicity"] != 1 for leg in selected):
            reasons.add("trade_cash_multiplicity_unresolved")
    all_refs = [o for values in refs.values() for o in values]
    if stock and set(map(key, refs["commission"])) != set(map(key, occurrences)):
        reasons.add("stock_fee_occurrence_set_conflict")
    if previous and previous[1]["operation"] != "retire" and decision.operation == "accept":
        from hermes_finance.services.broker_money import proof_blockers

        accepted_refs = [
            o
            for o in previous[1]["occurrences"]
            if o["role"] == "trade" and o["target_id"] == trade.id
        ]
        if set(map(key, accepted_refs)) == set(map(key, all_refs)) and not proof_blockers(
            session, *previous
        ):
            current = trades._candidate(session, trades._context(session), trade.source_identity)
            if not current["conflicts"] and current["action"] == "noop" and not reasons:
                return {
                    "target_id": trade.id,
                    "action": "reuse",
                    "candidate": current,
                    "cash_proof": previous[2]["cash_proof"],
                    "occurrences": all_refs,
                    "native_ids": candidate["ids"],
                    "source_identity": trade.source_identity,
                    "expected_trade_revision": candidate["revision"],
                }
    if len(set(map(key, all_refs))) != len(all_refs) or prior_keys - set(map(key, all_refs)):
        reasons.add("trade_cash_occurrence_set_conflict")
    for role, values in refs.items():
        if Counter(o["import_id"] for o in values) != Counter(o["import_id"] for o in occurrences):
            reasons.add("overlapping_trade_cash_missing_or_ambiguous")
        for ref in values:
            matching = [o for o in inventory if key(o["occurrence"]) == key(ref)]
            if (
                len(matching) != 1
                or matching[0]["occurrence"]["row_fingerprint"] != ref["row_fingerprint"]
            ):
                reasons.add("trade_cash_source_occurrence_changed")
        if conflicts(session, values, "trade", trade.id):
            reasons.add("occurrence_already_owned")
    reviewed = digest(
        [
            context,
            decision.seed.model_dump(),
            material(trade),
            material(instrument),
            candidate,
            refs,
            observation,
        ]
    )
    result.update(
        review_context_digest=reviewed,
        occurrences=all_refs,
        native_ids=candidate["ids"],
        source_identity=trade.source_identity,
        expected_trade_revision=candidate["revision"],
        cash_review={
            "settlement": groups["settlement"][0]["amount"]
            if len(groups["settlement"]) == 1
            else None,
            **({} if stock else {"paid_nkd": observation["signed_amount"]}),
            "commission": groups["commission"][0]["amount"]
            if len(groups["commission"]) == 1
            else None,
            "native_total": candidate["core"]["trade_amount"],
            **({} if stock else {"native_nkd": evidence["accrued_interest"]}),
            "native_fee": evidence["bank_commission"],
            "settlement_date": evidence["settlement_date"],
            "depo_settlement_date": evidence["depo_settlement_date"],
        },
    )
    claims = decision.trade_claims
    if claims is not None and not isinstance(claims, StockFeeClaims if stock else TradeCashClaims):
        reasons.add("trade_cash_proof_variant_unsupported")
        return result
    if claims is None or claims.review_context_digest != reviewed:
        reasons.add("trade_cash_claim_binding_required")
    if claims is None:
        reasons.add("commission_basis_unresolved" if stock else "paid_nkd_basis_unresolved")
        return result
    proof = {
        "claims": claims.model_dump(mode="json"),
        "source_identity": trade.source_identity,
        "native_ids": candidate["ids"],
        **(
            {}
            if stock
            else {
                "nkd_leg": {
                    "role": "paid_nkd",
                    "source_account": trade.source_account,
                    "effective_date": observation["date"],
                    "currency": observation["currency"],
                    "amount_minor": abs(observation["amount_minor"] or 0),
                    "direction": "debit",
                    "source_amount": observation["signed_amount"],
                    "occurrences": [
                        {
                            "import_id": o["import_id"],
                            "ordinal": o["ordinal"],
                            "source_fingerprint": o["row_fingerprint"],
                        }
                        for o in occurrences
                    ],
                    "observed_multiplicity": 1,
                }
            }
        ),
        "signed_minor": {
            role: str(exact_minor(values[0]["amount"])) if len(values) == 1 else None
            for role, values in groups.items()
        },
    }
    proof["signed_minor"]["native_total"] = str(exact_minor(candidate["core"]["trade_amount"]))
    if stock:
        proof["proof_variant"] = STOCK_FEE
        proof["signed_minor"]["native_fee"] = str(exact_minor(evidence["bank_commission"]))
    source = trades._context(session)["projections"][trade.source_identity]
    reasons.update(cash_reasons(source, groups, proof))
    result["cash_proof"] = proof
    if not reasons:
        reconciled = trades._candidate(
            session, trades._context(session), trade.source_identity, cash_proof=proof
        )
        reasons.update(reconciled["conflicts"])
        result["candidate"] = reconciled
        result["action"] = "reuse" if reconciled["action"] == "noop" else "revise"
    return result
