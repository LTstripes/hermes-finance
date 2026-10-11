"""Original-bound source -> one atomic, possibly incomplete broker-month DRAFT.

No generic Money classifier (#778), owner attestation, return authority or
second cash/trade ledger. Readiness is also consumed by the global Close.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from sqlalchemy import select, update

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import (
    Account,
    BrokerMonthApply,
    CashBalance,
    DepositSnapshot,
    ExecutedTrade,
    ExecutedTradeApply,
    ExecutedTradeOccurrence,
    ExecutedTradeRevision,
    ExternalFlow,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services import executed_trades, mybroker_identity, mybroker_import
from hermes_finance.services.mybroker_dispositions import effective_bindings, resolve
from hermes_finance.services.source_native import (
    NATIVE_SOURCE,
    native_quantity_representable,
    stage_native_position,
)
from hermes_finance.statement_import.mybroker import (
    MyBrokerError,
    canonical,
    digest,
)
from hermes_finance.statement_import.mybroker_identity import parse_identity

CONTRACT = "broker_month_v1"


def _minor(value: str | None, *, signed=False) -> int | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 100
        amount = Decimal(value) * 100
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise MyBrokerError("fractional_kopeck")
        if abs(amount) > 2**63 - 1 or (not signed and amount < 0):
            raise MyBrokerError("source_amount_out_of_range")
        return int(amount)


def _rows(session, model):
    return list(
        session.scalars(
            select(model)
            .order_by(*model.__table__.primary_key)
            .execution_options(populate_existing=True)
        )
    )


def _dependencies(session):
    # Identity's revision binds source/correction/disposition/mapping journals.
    # All current financial consumers of this batch bind the same confirmation.
    state = {"identity_revision": mybroker_identity._revision(session)}
    for model in (
        ReportingMonth,
        CashBalance,
        PositionSnapshot,
        InvestmentCashFlow,
        ExternalFlow,
        DepositSnapshot,
        ExecutedTrade,
        ExecutedTradeOccurrence,
        ExecutedTradeRevision,
        ExecutedTradeApply,
        BrokerMonthApply,
    ):
        state[model.__tablename__] = [
            [str(getattr(row, c.name)) for c in model.__table__.columns]
            for row in _rows(session, model)
        ]
    return digest(state)


def _bindings(identity):
    return [
        {
            "kind": "account",
            "identity": p["identity"],
            "hermes_id": p["hermes_id"],
            "mapping_id": p["mapping_id"],
        }
        for p in identity["accounts"]
    ] + [
        {
            "kind": "instrument",
            "identity": p["isin"],
            "hermes_id": p["hermes_id"],
            "mapping_id": p["mapping_id"],
        }
        for p in identity["instruments"]
    ]


def _controls(document, session=None):
    blockers = set(document["syntax_blockers"]) | set(document["endpoint_conflicts"])
    blockers.update(b for b in document["endpoint_blockers"] if b != "endpoint_value_unavailable")
    if any(p["ending_value"] is None for p in document["positions"]):
        blockers.add("ending_value_unavailable")
    cash = document["rub_money"]
    cash_delta = None
    if len(cash) == 1 and all(
        cash[0][f] is not None for f in ("beginning_amount", "ending_amount")
    ):
        posted = sum(_minor(m["amount"], signed=True) for m in document["money"])
        cash_delta = _minor(cash[0]["ending_amount"]) - _minor(cash[0]["beginning_amount"]) - posted
        if cash_delta != 0:
            blockers.add("cash_control_mismatch")
    else:
        blockers.add("rub_money_incomplete")
    quantity_controls = []
    if not document["positions"]:
        blockers.add("security_inventory_unproven")
    if any(
        t["core"]["isin"] not in {p["isin"] for p in document["positions"]}
        for t in document["trades"]
    ):
        blockers.add("quantity_control_unavailable")
    for trade in document["trades"]:
        from hermes_finance.services.broker_trade_money import effective_proof

        proof = (
            effective_proof(session, trade["identity"]) if session and trade["identity"] else None
        )
        groups = {
            kind: [leg for leg in trade.get("cash_legs", []) if leg["kind"] == kind]
            for kind in ("settlement", "commission")
        }
        if proof:
            leg = proof["nkd_leg"]
            groups["paid_nkd"] = [
                {
                    "amount": leg["source_amount"],
                    "date": leg["effective_date"],
                    "currency": leg["currency"],
                }
            ]
        readiness = executed_trades.source_bookkeeping_readiness(
            trade,
            groups,
            cash_proof=proof,
        )
        blockers.update(code for reasons in readiness.values() for code in reasons)
    for row in document["positions"]:
        delta = None
        if row["beginning_actual_quantity"] is not None:
            with localcontext() as ctx:
                ctx.prec = 100
                movement = sum(
                    (
                        Decimal(t["core"]["quantity"])
                        for t in document["trades"]
                        if t["core"]["source_account"] == row["source_account"]
                        and t["core"]["isin"] == row["isin"]
                        and t["state"] == "settled"
                        and t["depo_settlement_date"] is not None
                        and document["covered_from"]
                        <= t["depo_settlement_date"]
                        <= document["covered_to"]
                    ),
                    Decimal(0),
                )
                delta = (
                    Decimal(row["actual_quantity"])
                    - Decimal(row["beginning_actual_quantity"])
                    - movement
                )
            if delta:
                blockers.add("quantity_control_mismatch")
        else:
            blockers.add("quantity_control_unavailable")
        if Decimal(row["actual_quantity"]) != Decimal(row["forward_quantity"]):
            blockers.add("endpoint_unsettled")
        quantity_controls.append(
            {"isin": row["isin"], "difference": None if delta is None else str(delta)}
        )
    return sorted(blockers), cash_delta, quantity_controls


def _economics(document):
    return {
        "positions": sorted(
            [
                [p["isin"], str(Decimal(p["actual_quantity"]).normalize()), p["ending_value"]]
                for p in document["positions"]
            ]
        ),
        "cash": [r["ending_amount"] for r in document["rub_money"]],
    }


def _overlap(session, document, account_id):
    conflicts = set()
    for source in _rows(session, MyBrokerImport):
        bindings = effective_bindings(session, source)
        if not any(b["kind"] == "account" and b["hermes_id"] == account_id for b in bindings):
            continue
        prior = json.loads(source.normalized_json)
        if source.covered_to.isoformat() == document["covered_to"] and _economics(
            prior
        ) != _economics(document):
            conflicts.add("overlapping_endpoint_conflict")
    return conflicts


def _intersecting_sources(session, document, account_id):
    for source in _rows(session, MyBrokerImport):
        if (
            source.covered_from.isoformat() <= document["covered_to"]
            and source.covered_to.isoformat() >= document["covered_from"]
            and any(
                b["kind"] == "account" and b["hermes_id"] == account_id
                for b in effective_bindings(session, source)
            )
        ):
            yield source


def _prepare(session, *, document, filename, reporting_month_id, account_id, optional_hashes):
    parsed = mybroker_import.parse_import_original(session, document, filename)
    evidence = parse_identity(document, filename)
    # Effective aliases are authority already; only unbound aliases are proposed.
    # These proposals are zero-write until Apply receives the exact reviewed set.
    existing = mybroker_identity._prepare(session, evidence, [])
    account_bindings = [
        {"identity": p["identity"], "hermes_id": account_id}
        for p in existing["accounts"]
        if p["mapping_id"] is None
    ]
    identity = mybroker_identity._prepare(session, evidence, account_bindings)
    account_aliases = []
    for proposal in identity["accounts"]:
        alias = proposal["identity"]
        target = session.get(Account, proposal["hermes_id"]) if proposal["hermes_id"] else None
        account_aliases.append(
            {
                **proposal,
                "origins": (["filename_account"] if alias == evidence["filename_account"] else [])
                + (["acc_code"] if alias in evidence["row_accounts"] else []),
                "target_name": target.name if target else None,
            }
        )
    source = mybroker_import._prepare(session, parsed, planned_bindings=_bindings(identity))
    month = session.get(ReportingMonth, reporting_month_id, populate_existing=True)
    if month is None:
        raise MyBrokerError("reporting_month_not_found")
    conflicts = set(identity["conflicts"]) | set(source["conflicts"])
    if any(p["hermes_id"] != account_id for p in identity["accounts"]):
        conflicts.add("account_mapping_conflict")
    conflicts.update(g["code"] for g in identity["evidence_gaps"])
    if not identity["can_stage"]:
        conflicts.add("identity_batch_conflict")
    if month.status != "draft":
        conflicts.add("reporting_month_closed")
    if (parsed["covered_from"], parsed["covered_to"]) != (
        month.period_start.isoformat(),
        month.period_end.isoformat(),
    ) or month.snapshot_date != month.period_end:
        conflicts.add("source_month_range_mismatch")
    if any(i["currency"] != "RUB" for i in identity["instruments"]):
        conflicts.add("instrument_currency_unsupported")
    account = session.get(Account, account_id)
    if (
        account is None
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        conflicts.add("account_binding_invalid")
    conflicts.update(_overlap(session, parsed, account_id))
    identities = {t["identity"] for t in parsed["trades"] if t["identity"]}
    if len(identities) > 1000:
        conflicts.add("canonical_trade_selection_limit")
    known = [
        t.source_identity for t in _rows(session, ExecutedTrade) if t.source_identity in identities
    ]
    canonical_blockers = set()
    if known:
        for candidate in executed_trades._plan(session, known)["candidates"]:
            conflicts.update(candidate["conflicts"])
            canonical_blockers.update(_bookkeeping_trade_blockers(candidate))
            if candidate["action"] == "noop" and not _canonical_projection_matches(
                session, candidate
            ):
                canonical_blockers.add("canonical_trade_projection_changed")
    position_plan = []
    for p in parsed["positions"]:
        proposal = next(i for i in identity["instruments"] if i["isin"] == p["isin"])
        value = _minor(p["ending_value"])
        quantity = Decimal(p["actual_quantity"])
        if (
            quantity < 0
            or (proposal["instrument_type"] == "stock" and quantity != quantity.to_integral_value())
            or quantity > Decimal("999999999999.999999")
            or quantity.normalize().as_tuple().exponent < -6
            or not native_quantity_representable(session, quantity)
        ):
            conflicts.add("quantity_precision_unsupported")
        if value is None or (quantity == 0 and value != 0):
            conflicts.add("ending_position_unavailable")
        row_key = digest(
            ["mybroker-native-position-v1", account_id, p["isin"], parsed["covered_to"]]
        )
        matches = list(
            session.scalars(
                select(PositionSnapshot).where(
                    PositionSnapshot.reporting_month_id == month.id,
                    PositionSnapshot.account_id == account_id,
                    PositionSnapshot.instrument_id == proposal["hermes_id"],
                )
            )
        )
        existing = matches[0] if len(matches) == 1 else None
        if matches and (
            quantity == 0
            or existing is None
            or existing.source_row_key != row_key
            or existing.price_source != NATIVE_SOURCE
            or existing.quantity != quantity
            or existing.market_value_kopecks != value
        ):
            conflicts.add("existing_position_reconciliation_required")
        position_plan.append(
            {
                "isin": p["isin"],
                "instrument_id": proposal["hermes_id"],
                "asset_kind": proposal["instrument_type"],
                "quantity": p["actual_quantity"],
                "market_value_kopecks": value,
                "source_row_key": row_key,
                "position_id": existing.id if existing else None,
                "action": "observed_zero"
                if quantity == 0 and value == 0
                else ("reuse" if existing else "create"),
            }
        )
    existing_positions = list(
        session.scalars(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == month.id,
                PositionSnapshot.account_id == account_id,
            )
        )
    )
    if any(row.id not in {p["position_id"] for p in position_plan} for row in existing_positions):
        conflicts.add("existing_position_reconciliation_required")
    cash_rows = list(
        session.scalars(
            select(CashBalance).where(
                CashBalance.reporting_month_id == month.id,
                CashBalance.account_id == account_id,
            )
        )
    )
    cash_amount = (
        _minor(parsed["rub_money"][0]["ending_amount"]) if len(parsed["rub_money"]) == 1 else None
    )
    if cash_amount is None:
        conflicts.add("ending_cash_unavailable")
    owned_cash = {
        json.loads(r.projection_json)["cash_id"]
        for r in _rows(session, BrokerMonthApply)
        if r.reporting_month_id == month.id
        and r.account_id == account_id
        and "cash_id" in json.loads(r.projection_json)
    }
    cash_id = cash_rows[0].id if len(cash_rows) == 1 else None
    if cash_rows and (
        cash_id not in owned_cash
        or len(cash_rows) != 1
        or cash_rows[0].amount_kopecks != cash_amount
        or cash_rows[0].currency != "RUB"
        or not cash_rows[0].include_in_capital
    ):
        conflicts.add("existing_cash_reconciliation_required")
    blockers, cash_delta, quantity_controls = _controls(parsed, session)
    blockers.extend(canonical_blockers)
    # Preview must disclose the same already accepted intersecting authority
    # that GET and Close consume, even when the new original itself is clean.
    other_identities = set()
    for other in _intersecting_sources(session, parsed, account_id):
        other_plan = mybroker_import._prepare(session, json.loads(other.normalized_json))
        conflicts.update(other_plan["conflicts"])
        blockers.extend(other_plan["blockers"])
        other_identities.update(
            t["identity"] for t in other_plan["document"]["trades"] if t["identity"]
        )
    if other_identities - identities:
        try:
            for candidate in executed_trades._plan(session, sorted(other_identities - identities))[
                "candidates"
            ]:
                conflicts.update(candidate["conflicts"])
                blockers.extend(_bookkeeping_trade_blockers(candidate))
                if candidate["action"] != "noop" or not _canonical_projection_matches(
                    session, candidate
                ):
                    blockers.append("canonical_trade_projection_changed")
        except MyBrokerError:
            blockers.append("canonical_trade_authority_unavailable")
    if _existing_flows(session, month.id, account_id):
        blockers.append("existing_flow_reconciliation_required")
    blockers.extend(_account_readiness(session, month.id, account_id))
    blockers = sorted(
        set(blockers)
        | set(source["blockers"])
        | ({"optional_evidence_unsupported"} if optional_hashes else set())
    )
    material = {
        "contract_version": CONTRACT,
        "reporting_month_id": month.id,
        "account_id": account_id,
        "document": parsed,
        "identity": identity,
        "account_bindings": account_bindings,
        "account_aliases": account_aliases,
        "positions": position_plan,
        "cash_kopecks": cash_amount,
        "cash_id": cash_id,
        "optional_hashes": optional_hashes,
        "exceptions": blockers,
        "conflicts": sorted(conflicts),
        "cash_control_difference_kopecks": cash_delta,
        "quantity_controls": quantity_controls,
        "dependency_digest": _dependencies(session),
    }
    return {
        **material,
        "confirmation_digest": digest(material),
        "can_apply": not conflicts,
        "bookkeeping_ready": not blockers and not conflicts,
        "coverage_state": "unknown",
        "indicative_return_ready": False,
        "exact_return_ready": False,
        "opening_date": (
            date.fromisoformat(parsed["covered_from"]) - timedelta(days=1)
        ).isoformat(),
        "ending_date": parsed["covered_to"],
    }


def preview_broker_month(session, **kwargs):
    with coherent_read_snapshot(session):
        return _prepare(session, **kwargs)


def _projection(session, receipt):
    rows = []
    for model in (PositionSnapshot, CashBalance):
        for row in session.scalars(
            select(model)
            .where(
                model.reporting_month_id == receipt.reporting_month_id,
                model.account_id == receipt.account_id,
            )
            .order_by(model.id)
            .execution_options(populate_existing=True)
        ):
            rows.append(
                [
                    model.__tablename__,
                    [
                        str(getattr(row, c.name))
                        for c in model.__table__.columns
                        if c.name not in {"updated_at", "notes"}
                    ],
                ]
            )
    month = session.get(ReportingMonth, receipt.reporting_month_id, populate_existing=True)
    return digest([rows, str(month.snapshot_date), str(month.period_start), str(month.period_end)])


def _existing_flows(session, month_id, account_id):
    from hermes_finance.services.broker_money import owned_payout_ids

    owned = owned_payout_ids(session, month_id, account_id)
    return (
        any(
            row.id not in owned
            for row in session.scalars(
                select(InvestmentCashFlow).where(
                    InvestmentCashFlow.reporting_month_id == month_id,
                    InvestmentCashFlow.account_id == account_id,
                )
            )
        )
        or session.scalar(
            select(ExternalFlow.id).where(
                ExternalFlow.reporting_month_id == month_id, ExternalFlow.account_id == account_id
            )
        )
        is not None
    )


def _source_money_blockers(session, source, plan):
    """Resolve the generic code only through every exact unsupported occurrence."""
    from hermes_finance.services.broker_money import effective_occurrence

    blockers = set(plan["blockers"])
    unresolved = [
        row
        for row in plan["document"]["money"]
        if row["kind"] == "unsupported" and not effective_occurrence(session, source.id, row)
    ]
    if not unresolved:
        blockers.discard("money_semantics_unsupported")
    # S1 remains immutable and reports nonzero fees as unknown. Resolve only
    # this named fee limitation, after rechecking every affected native trade.
    from hermes_finance.services.broker_trade_money import effective_proof

    nonzero = [
        t
        for t in plan["document"]["trades"]
        if t["bank_commission"] is not None and Decimal(t["bank_commission"]) != 0
    ]
    if nonzero and all(t["identity"] and effective_proof(session, t["identity"]) for t in nonzero):
        blockers.discard("commission_basis_unresolved")
    return blockers


def _bookkeeping_trade_blockers(candidate):
    readiness = candidate["evidence"]["readiness"]
    # C1 and historical coverage are return-authority gates, not bookkeeping.
    return {
        code
        for kind in ("settlement", "commission", "cash_ownership", "unsupported")
        for code in readiness[kind]
    }


def _canonical_projection_matches(session, candidate):
    latest = session.scalar(
        select(ExecutedTradeRevision)
        .where(ExecutedTradeRevision.trade_id == candidate["trade_id"])
        .order_by(ExecutedTradeRevision.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if (
        latest is None
        or latest.acceptance_state != "active"
        or json.loads(latest.evidence_json) != candidate["evidence"]
    ):
        return False
    for occurrence in candidate["evidence"]["occurrences"]:
        link = session.scalar(
            select(ExecutedTradeOccurrence)
            .where(
                ExecutedTradeOccurrence.import_id == occurrence["import_id"],
                ExecutedTradeOccurrence.section == occurrence["section"],
                ExecutedTradeOccurrence.ordinal == occurrence["ordinal"],
            )
            .execution_options(populate_existing=True)
        )
        if (
            link is None
            or link.trade_id != candidate["trade_id"]
            or link.source_fingerprint != occurrence["source_fingerprint"]
        ):
            return False
    return True


def _readiness(session, receipt):
    accepted = json.loads(receipt.projection_json)
    if accepted.get("contract_version") == "broker_money_dependency_v1":
        return []
    if accepted.get("contract_version") == "broker_money_v1":
        from hermes_finance.services.broker_money import latest_proofs, proof_blockers, target_key

        latest = latest_proofs(session)
        return sorted(
            {
                code
                for target in accepted["targets"]
                for code in proof_blockers(session, *latest[target_key(target)])
            }
        )
    blockers = set(accepted["exceptions"])
    source = session.get(MyBrokerImport, receipt.import_id, populate_existing=True)
    account = session.get(Account, receipt.account_id, populate_existing=True)
    if (
        account is None
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        blockers.add("account_binding_changed")
    if _projection(session, receipt) != accepted["projection_digest"]:
        blockers.add("source_projection_changed")
    if _existing_flows(session, receipt.reporting_month_id, receipt.account_id):
        blockers.add("existing_flow_reconciliation_required")
    if (
        source is None
        or digest([source.normalized_json, source.mappings_json, source.parser_version])
        != accepted["source_digest"]
    ):
        blockers.add("source_authority_changed")
    else:
        parsed = json.loads(source.normalized_json)
        trade_identities = set(accepted["trade_identities"])
        # Recompute original source dependencies with the same S1 reconciliation.
        current = mybroker_import._prepare(session, json.loads(source.normalized_json))
        blockers.update(current["conflicts"])
        blockers.update(_source_money_blockers(session, source, current))
        source_blockers, _, _ = _controls(current["document"], session)
        blockers.update(source_blockers)
        if current["missing_mappings"]:
            blockers.add("accepted_mapping_changed")
        if effective_bindings(session, source) != json.loads(source.mappings_json) or resolve(
            session, source
        ):
            blockers.add("source_disposition_changed")
        blockers.update(_overlap(session, parsed, receipt.account_id))
        for binding in json.loads(source.mappings_json):
            if binding["kind"] == "instrument":
                instrument = session.get(Instrument, binding["hermes_id"], populate_existing=True)
                expected = accepted["instruments"].get(str(binding["hermes_id"]))
                if (
                    instrument is None
                    or [instrument.isin, instrument.instrument_type, instrument.currency]
                    != expected
                ):
                    blockers.add("instrument_metadata_changed")
        # Any newly accepted intersecting source stays relevant to this account,
        # including opaque/unlinked rows. A zero net cash control cannot clear it.
        for other in _intersecting_sources(session, parsed, receipt.account_id):
            other_plan = mybroker_import._prepare(session, json.loads(other.normalized_json))
            blockers.update(other_plan["conflicts"])
            blockers.update(_source_money_blockers(session, other, other_plan))
            trade_identities.update(
                t["identity"] for t in other_plan["document"]["trades"] if t["identity"]
            )
        if trade_identities:
            try:
                plan = executed_trades._plan(session, sorted(trade_identities))
                for candidate in plan["candidates"]:
                    blockers.update(candidate["conflicts"])
                    blockers.update(_bookkeeping_trade_blockers(candidate))
                    if candidate["action"] != "noop" or (
                        candidate["source_identity"] in accepted["trade_identities"]
                        and candidate["trade_id"] not in accepted["trade_ids"]
                    ):
                        blockers.add("canonical_trade_projection_changed")
                    if not _canonical_projection_matches(session, candidate):
                        blockers.add("canonical_trade_projection_changed")
            except MyBrokerError:
                blockers.add("canonical_trade_authority_unavailable")
    return sorted(blockers)


def _account_readiness(session, month_id, account_id):
    """Retained receipt authority is account-wide, as at global Close."""
    receipts = session.scalars(
        select(BrokerMonthApply)
        .where(
            BrokerMonthApply.reporting_month_id == month_id,
            BrokerMonthApply.account_id == account_id,
        )
        .execution_options(populate_existing=True)
    )
    return sorted({code for receipt in receipts for code in _readiness(session, receipt)})


def broker_month_close_blockers(session, month_id):
    """One shared pure read for readiness and reserved authoritative Close."""
    result = []
    for receipt in session.scalars(
        select(BrokerMonthApply)
        .where(BrokerMonthApply.reporting_month_id == month_id)
        .execution_options(populate_existing=True)
    ):
        for code in _readiness(session, receipt):
            explanation = {
                "money_semantics_unsupported": "есть неразобранные денежные движения",
                "settlement_cash_missing_or_ambiguous": "денежные расчёты по сделке не подтверждены",
                "cash_control_mismatch": "денежные движения не сходятся с остатками",
                "quantity_control_mismatch": "движения бумаг не сходятся с остатками",
                "source_projection_changed": "сохранённые позиции или cash отличаются от источника",
                "canonical_trade_projection_changed": "связь сделки с источником требует сверки",
                "optional_evidence_unsupported": "дополнительный документ требует подтверждённого чтения",
                "existing_flow_reconciliation_required": "существующие денежные события требуют сверки с источником",
            }.get(code, "доказательства источника требуют сверки в разделе MyBroker")
            pair = (code, f"MyBroker счёт #{receipt.account_id}: {explanation}.")
            if pair not in result:
                result.append(pair)
    return tuple(result)


def read_broker_month(session, request_id):
    with coherent_read_snapshot(session):
        receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
        if receipt is None:
            raise MyBrokerError("broker_month_not_found")
        accepted = json.loads(receipt.projection_json)
        if accepted.get("contract_version") == "broker_money_dependency_v1":
            raise MyBrokerError("broker_month_not_found")
        if accepted.get("contract_version") == "broker_money_v1":
            from hermes_finance.services.broker_money import read_money

            return read_money(session, request_id)
        blockers = _account_readiness(session, receipt.reporting_month_id, receipt.account_id)
        source = session.get(MyBrokerImport, receipt.import_id)
        accepted["document"] = (
            json.loads(source.normalized_json)
            if source is not None
            and digest([source.normalized_json, source.mappings_json, source.parser_version])
            == accepted["source_digest"]
            else None
        )
        from hermes_finance.services.broker_money import read_money, receipts

        money_receipts = [
            r
            for r, proof in receipts(session)
            if r.reporting_month_id == receipt.reporting_month_id
            and r.account_id == receipt.account_id
            and proof["base_request_id"] == request_id
        ]
        money = read_money(session, money_receipts[-1].request_id) if money_receipts else None
        return {
            "contract_version": CONTRACT,
            "request_id": receipt.request_id,
            "reporting_month_id": receipt.reporting_month_id,
            "account_id": receipt.account_id,
            "import_id": receipt.import_id,
            "confirmation_digest": receipt.confirmation_digest,
            "status": session.get(ReportingMonth, receipt.reporting_month_id).status,
            "accepted": accepted,
            "money_acceptance": money,
            "exceptions": blockers,
            "bookkeeping_ready": not blockers,
            "coverage_state": "unknown",
            "indicative_return_ready": False,
            "exact_return_ready": False,
        }


def apply_broker_month(
    session, *, confirmation_digest, request_id, reviewed_account_bindings=None, **kwargs
):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    reviewed = sorted(reviewed_account_bindings or [], key=lambda b: b["identity"])
    fingerprint_material = [
        hashlib.sha256(kwargs["document"]).hexdigest(),
        kwargs["filename"],
        kwargs["reporting_month_id"],
        kwargs["account_id"],
        kwargs["optional_hashes"],
        confirmation_digest,
    ]
    # Preserve existing all-mapped receipt retries, which had no new decisions.
    if reviewed:
        fingerprint_material.append(reviewed)
    fingerprint = digest(fingerprint_material)
    session.rollback()
    try:
        session.execute(
            update(BrokerMonthApply)
            .where(BrokerMonthApply.request_id == "")
            .values(request_id=BrokerMonthApply.request_id)
        )
        session.expire_all()
        receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
        duplicate = receipt is not None
        if receipt:
            if receipt.request_fingerprint != fingerprint:
                raise MyBrokerError("idempotency_conflict")
            session.rollback()
        else:
            plan = _prepare(session, **kwargs)
            if plan["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("broker_month_preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError("broker_month_reconciliation_required")
            if reviewed != sorted(plan["account_bindings"], key=lambda b: b["identity"]):
                raise MyBrokerError("broker_month_account_bindings_unconfirmed")
            mybroker_identity.stage_identity(
                session,
                document=kwargs["document"],
                filename=kwargs["filename"],
                account_bindings=plan["account_bindings"],
                confirmation_digest=plan["identity"]["confirmation_digest"],
            )
            source = mybroker_import.stage_mybroker(
                session,
                mybroker_import.parse_import_original(
                    session, kwargs["document"], kwargs["filename"]
                ),
            )
            parsed = json.loads(source.normalized_json)
            identities = sorted({t["identity"] for t in parsed["trades"] if t["identity"]})
            trade_ids = []
            if identities:
                trade_plan = executed_trades._plan(session, identities)
                trade_ids = executed_trades.stage_executed_trades(
                    session,
                    trade_plan,
                    confirmation_digest=trade_plan["confirmation_digest"],
                    request_id=digest([CONTRACT, request_id]),
                )
            position_ids = []
            for p in plan["positions"]:
                if p["action"] == "observed_zero":
                    continue  # Affirmative source zero is retained in S1, never a fabricated holding.
                row = (
                    session.get(PositionSnapshot, p["position_id"])
                    if p["position_id"]
                    else stage_native_position(
                        session,
                        reporting_month_id=plan["reporting_month_id"],
                        account_id=plan["account_id"],
                        instrument_id=p["instrument_id"],
                        quantity=p["quantity"],
                        market_value=RubleAmount(p["market_value_kopecks"]),
                        price_date=date.fromisoformat(parsed["covered_to"]),
                        source_import_id=source.id,
                        source_row_key=p["source_row_key"],
                        asset_kind=p["asset_kind"],
                        bond_nkd_basis="unknown" if p["asset_kind"] == "bond" else "not_applicable",
                    )
                )
                position_ids.append(row.id)
            cash = (
                session.get(CashBalance, plan["cash_id"])
                if plan["cash_id"]
                else CashBalance(
                    reporting_month_id=plan["reporting_month_id"],
                    account_id=plan["account_id"],
                    name="MyBroker RUB",
                    amount_kopecks=plan["cash_kopecks"],
                    currency="RUB",
                    include_in_capital=True,
                )
            )
            session.add(cash)
            session.flush()
            receipt = BrokerMonthApply(
                request_id=request_id,
                request_fingerprint=fingerprint,
                confirmation_digest=confirmation_digest,
                reporting_month_id=plan["reporting_month_id"],
                account_id=plan["account_id"],
                import_id=source.id,
                projection_json="{}",
                accepted_at=datetime.now(UTC),
            )
            accepted = {
                # Preserve supplied, still-unread optional evidence. Source,
                # controls and authority are recomputed from immutable S1 and
                # current canonical facts; a pre-enrichment failure must not
                # become a permanent receipt exception after successful Apply.
                "exceptions": ["optional_evidence_unsupported"]
                if kwargs["optional_hashes"]
                else [],
                "position_ids": position_ids,
                "cash_id": cash.id,
                "trade_ids": trade_ids,
                "trade_identities": identities,
                "source_digest": digest(
                    [source.normalized_json, source.mappings_json, source.parser_version]
                ),
                "projection_digest": _projection(session, receipt),
                "instruments": {
                    str(i["hermes_id"]): [i["isin"], i["instrument_type"], i["currency"]]
                    for i in plan["identity"]["instruments"]
                },
                "optional_hashes": kwargs["optional_hashes"],
                "cash_control_difference_kopecks": plan["cash_control_difference_kopecks"],
                "quantity_controls": plan["quantity_controls"],
            }
            receipt.projection_json = canonical(accepted)
            session.add(receipt)
            session.commit()
    except BaseException:
        session.rollback()
        raise
    return {**read_broker_month(session, request_id), "duplicate": duplicate}
