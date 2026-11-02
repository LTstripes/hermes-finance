"""Offline preparation of bounded Money decisions; existing review/Apply owns authority."""

import hashlib
import json

from sqlalchemy import select

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain.broker_money import MoneyIntentV2
from hermes_finance.domain.money_security import parse_money_security
from hermes_finance.persistence import Account, BrokerIdentityMapping, InvestmentCashFlow
from hermes_finance.services import broker_money
from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
from hermes_finance.services.mybroker_money_candidates import _narratives
from hermes_finance.services.source_money_classifications import default_classification
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError


def _own_accounts(session):
    accounts = {a.id for a in session.scalars(select(Account)) if a.status == "active"}
    return {
        m.provider_identity: m.hermes_account_id
        for m in session.scalars(select(BrokerIdentityMapping))
        if m.provider == PROVIDER
        and m.subject_kind == "account"
        and m.status == "effective"
        and m.hermes_account_id in accounts
    }


def prepare_money(session, intent: MoneyIntentV2, originals):
    """Return source-bound choices plus the ordinary guarded Preview, with zero writes.

    Do not manufacture Owner claims, recognize a payment by proximity or create
    a second writer. Equal PDF/XML facts are candidates for explicit same-event
    review. Unknown rows and internal transfers still need their supported proof.
    """
    if intent.money_decisions:
        raise MyBrokerError("money_preparation_requires_empty_decisions")
    with coherent_read_snapshot(session):
        initial = broker_money._plan(session, intent, originals)
        global_blockers = set(initial["blockers"]) - {"money_decisions_required"}
        resolver = MoneyInstrumentResolver(session)
        own = _own_accounts(session)
        by_hash = {hashlib.sha256(data).hexdigest(): data for _, data in originals}
        narratives = {}
        for source in initial["sources"]:
            data = by_hash.get(source["source"]["document_sha256"])
            if data is None:
                continue
            document = json.loads(source["source"]["normalized_json"])
            for row, (operation, narrative, _) in zip(
                document["money"], _narratives(data), strict=True
            ):
                narratives[(source["import_id"], row["ordinal"])] = (operation, narrative)
        payouts = list(session.scalars(select(InvestmentCashFlow).order_by(InvestmentCashFlow.id)))
        decisions, rows, seen = [], [], set()
        for observation in initial["inventory"]:
            occurrence = observation["occurrence"]
            row = observation["row"]
            operation, narrative = narratives[(occurrence["import_id"], occurrence["ordinal"])]
            classification = default_classification(
                operation,
                narrative,
                row["kind"],
                row["amount"],
                source_account=row["source_account"],
                selected_accounts=set(own),
            )
            amount = observation["amount_minor"]
            # These describe missing review, not failed source integrity. Keep
            # them visible; the ordinary Preview still enforces every claim.
            review_findings = {
                "money_semantics_unsupported",
                "summary_proof_unavailable",
                "economic_identity_unproven",
                "instrument_link_unproven",
                "owner_crossing_unproven",
                "portfolio_externality_unproven",
            }
            reasons = set(global_blockers) | (set(observation["reasons"]) - review_findings)
            if amount is None or amount == 0 or row["currency"] != "RUB":
                reasons.add("exact_nonzero_rub_required")
            elif (classification in {"coupon", "dividend", "external_deposit"} and amount < 0) or (
                classification in {"external_withdrawal", "fee", "tax"} and amount > 0
            ):
                classification = "unknown"
                reasons.add("money_direction_conflict")
            item = {
                "occurrence": occurrence,
                "classification": classification,
                "status": "needs_confirmation",
                "requires_confirmation": True,
                "review_findings": sorted(set(observation["reasons"]) & review_findings),
                "existing_payout_candidate_ids": [],
            }
            decision = None
            if classification in {"coupon", "dividend"}:
                security = parse_money_security(narrative)
                instrument_id, link_status = (
                    resolver.resolve(security) if security else (None, "not_parsed")
                )
                instrument = resolver.instruments.get(instrument_id)
                if (
                    security is None
                    or security.kind != classification
                    or instrument is None
                    or instrument.instrument_type
                    != ("bond" if classification == "coupon" else "stock")
                    or instrument.currency != "RUB"
                    or not instrument.is_active
                ):
                    reasons.add("exact_payout_instrument_required")
                elif not reasons:
                    decision = {
                        "role": classification,
                        "seed": {k: occurrence[k] for k in ("import_id", "section", "ordinal")},
                        "instrument_id": instrument_id,
                    }
                    item["existing_payout_candidate_ids"] = [
                        f.id
                        for f in payouts
                        if (
                            f.reporting_month_id,
                            f.account_id,
                            f.instrument_id,
                            f.flow_type,
                            f.event_date.isoformat(),
                            f.net_amount_kopecks,
                            f.currency,
                        )
                        == (
                            intent.reporting_month_id,
                            intent.account_id,
                            instrument_id,
                            classification,
                            observation["date"],
                            amount,
                            "RUB",
                        )
                    ]
                item["instrument_link_status"] = link_status
            elif (
                classification == "external_deposit"
                and observation["candidate_kind"] == "account_cash_in_candidate"
                and not reasons
            ):
                decision = {
                    "role": "account_funding",
                    "seed": {k: occurrence[k] for k in ("import_id", "section", "ordinal")},
                }
            elif classification == "internal_transfer":
                reasons.add("explicit_transfer_link_required")
            else:
                reasons.add("specific_money_review_required")
            if decision is not None:
                model = MoneyIntentV2.model_validate(
                    {**intent.model_dump(), "money_decisions": [decision]}
                )
                cohort_reasons = set()
                _, cohort = broker_money._cohort(
                    initial["inventory"],
                    model.money_decisions[0].seed,
                    initial["sources"],
                    cohort_reasons,
                )
                keys = {broker_money.key(o) for o in cohort}
                reasons.update(cohort_reasons)
                if not keys.intersection(seen):
                    seen.update(keys)
                    if not reasons:
                        decisions.append(decision)
                        item["status"] = "prepared"
                        item["decision"] = decision
            item["reason_codes"] = sorted(reasons)
            rows.append(item)
        prepared = MoneyIntentV2.model_validate(
            {**intent.model_dump(), "money_decisions": decisions}
        )
        preview = broker_money._plan(session, prepared, originals)
        return {
            "contract_version": "broker_money_preparation_v1",
            "intent": prepared.model_dump(mode="json"),
            "rows": rows,
            "preview": preview,
            "can_apply": preview["can_apply"],
        }
