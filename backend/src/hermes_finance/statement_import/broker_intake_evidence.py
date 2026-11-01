"""Bounded original-byte evidence for the ordinary statement intake.

No writer, financial projection or substitute S1 parser. Complete occurrence
sets are retained; an indistinguishable cohort never invents individual edges.
"""

import re
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import NS, digest, parse_mybroker
from hermes_finance.statement_import.mybroker_draft_structure import draft_structure_exceptions
from hermes_finance.statement_import.mybroker_metadata import parse_section_metadata

CONTRACT = "broker-intake-source-evidence-v1"
_FEE = re.compile(
    r"Банка по исполнению расчетов на ФР \(МБ и СПБ\) за "
    r"(?P<day>[0-9]{2}\.[0-9]{2}\.[0-9]{4}) \(ставка по тарифу 0,02%\)\."
)


def _text(value):
    return " ".join((value or "").split())


def _minor(value):
    if value is None:
        return None
    amount = Decimal(value) * 100
    if not amount.is_finite() or amount != amount.to_integral_value() or abs(amount) > 2**63 - 1:
        return None
    return int(amount)


def read_intake_evidence(document, filename, *, source=None):
    source = deepcopy(source) if source is not None else parse_mybroker(document, filename)
    if any("cash_legs" not in t for t in source["trades"]):
        from hermes_finance.services.mybroker_import import _attach_cash

        _attach_cash(source, {})
    if source["document_sha256"] != __import__("hashlib").sha256(document).hexdigest():
        raise ValueError("source_original_mismatch")
    root = ET.fromstring(document.decode("utf-8-sig"))
    structural = draft_structure_exceptions(document, source, repeated_occurrences=True)
    sections = parse_section_metadata(document, filename)["sections"]
    table = root.find("m:Trades/m:Report/m:Tablix2", NS)
    basis = bool(
        table is not None
        and _text(table.get("Textbox118")) == "⁸ В случае сделки по облигации, сумма включает НКД."
        and _text(table.get("Textbox73")) == "Комиссия банка"
        and _text(table.get("Textbox64")) == "Сумма сделки в валюте расчетов⁸"
    )
    raw_trades = root.findall("m:Trades/m:Report/m:Tablix2/m:Details_Collection/m:Details", NS)
    settled = [t for t in source["trades"] if t["section"] == "completed"]
    raw_money = root.findall(
        "m:Trades2/m:Report/m:Tablix1/m:settlement_date_Collection/"
        "m:settlement_date/m:rn_Collection/m:rn",
        NS,
    )
    if len(raw_trades) != len(settled) or len(raw_money) != len(source["money"]):
        raise ValueError("source_occurrence_inventory_changed")
    money = []
    for row, node in zip(source["money"], raw_money, strict=True):
        operation = node.find("m:oper_type", NS)
        comment = node.find("m:oper_type/m:comment", NS)
        money.append(
            {
                "row": row,
                "operation": operation.get("oper_type", ""),
                "description": comment.get("comment", ""),
                "row_fingerprint": digest(row),
            }
        )
    groups, candidates, issues = defaultdict(list), defaultdict(list), []
    if "unparsed_source_rows" in source["syntax_blockers"] and structural is None:
        issues.append({"code": "source_structure_review_required"})
    bond_isins = {
        n.get("ISIN1")
        for n in root.findall(".//m:Positions//m:Details", NS)
        if n.get("active_type") == "Облигации"
    }
    fees = []
    for item in money:
        row = item["row"]
        if row["kind"] != "unsupported":
            continue
        if item["operation"] == "НКД по сделке":
            key = (
                row["source_account"],
                row["date"],
                row["currency"],
                _minor(row["amount"]),
                _text(item["description"]),
            )
            candidates[key].append(item)
        elif item["operation"] == "Комиссия":
            match = _FEE.fullmatch(_text(item["description"]))
            if match and _minor(row["amount"]) is not None and _minor(row["amount"]) < 0:
                day = ".".join(reversed(row["date"].split("-")))
                if row["currency"] == "RUB" and match["day"] == day:
                    fees.append(
                        {
                            "ordinal": row["ordinal"],
                            "amount_minor": _minor(row["amount"]),
                            "date": row["date"],
                            "currency": "RUB",
                            "row_fingerprint": item["row_fingerprint"],
                        }
                    )
    for trade, node in zip(settled, raw_trades, strict=True):
        qty = Decimal(trade["core"]["quantity"])
        nkd = _minor(trade["accrued_interest"])
        fee = _minor(trade["bank_commission"])
        total = _minor(trade["core"]["trade_amount"])
        cash = {
            kind: [r for r in trade.get("cash_legs", []) if r["kind"] == kind]
            for kind in ("settlement", "commission")
        }
        valid = (
            basis
            and trade["core"]["isin"] in bond_isins
            and trade["identity"]
            and len(trade["ids"]) == 2
            and trade["state"] == "settled"
            and trade["depo_settlement_date"]
            and trade["core"]["currency"] == "RUB"
            and not trade["repo_observed"]
            and nkd is not None
            and nkd > 0
            and fee is not None
            and fee > 0
            and total is not None
            and total > 0
            and qty != 0
            and all(len(v) == 1 for v in cash.values())
        )
        if not valid:
            issues.append(
                {"code": "typed_bond_cash_evidence_required", "trade_identity": trade["identity"]}
            )
            continue
        direction = -1 if qty > 0 else 1
        principal, posted_fee = cash["settlement"][0], cash["commission"][0]
        if (
            any(
                r["currency"] != "RUB" or r["date"] != trade["settlement_date"]
                for r in (principal, posted_fee)
            )
            or _minor(principal["amount"]) != direction * (total - nkd)
            or _minor(posted_fee["amount"]) != -fee
        ):
            issues.append(
                {"code": "typed_bond_cash_control_mismatch", "trade_identity": trade["identity"]}
            )
            continue
        key = (
            trade["core"]["source_account"],
            trade["settlement_date"],
            "RUB",
            direction * nkd,
            "c " + _text(node.get("p_name")),
        )
        groups[key].append(trade)
    cohorts = []
    for key in sorted(groups):
        trades, rows = groups[key], candidates.get(key, [])
        if len(trades) != len(rows):
            issues.append(
                {
                    "code": "nkd_complete_occurrence_set_required",
                    "trade_identities": sorted(t["identity"] for t in trades),
                    "observed_occurrences": len(rows),
                    "expected_occurrences": len(trades),
                }
            )
            continue
        # Every matching native execution has the same signed NKD obligation.
        # The full multiset proves each execution's economics without claiming
        # which indistinguishable cash occurrence belongs to an individual ID.
        identities = sorted(t["identity"] for t in trades)
        occurrences = sorted(
            [
                {"ordinal": r["row"]["ordinal"], "row_fingerprint": r["row_fingerprint"]}
                for r in rows
            ],
            key=lambda r: r["ordinal"],
        )
        cohort = {
            "source_account": key[0],
            "date": key[1],
            "currency": key[2],
            "signed_nkd_minor": key[3],
            "trade_identities": identities,
            "occurrences": occurrences,
            "native_total_basis": "includes_paid_nkd",
            "direction": "buy" if key[3] < 0 else "sell",
        }
        cohort["cohort_digest"] = digest(cohort)
        cohorts.append(cohort)
    used = {r["ordinal"] for c in cohorts for r in c["occurrences"]}
    for rows in candidates.values():
        if any(r["row"]["ordinal"] not in used for r in rows):
            issues.append(
                {
                    "code": "unmatched_nkd_occurrence",
                    "ordinals": [
                        r["row"]["ordinal"] for r in rows if r["row"]["ordinal"] not in used
                    ],
                }
            )
    return {
        "contract_version": CONTRACT,
        "document_sha256": source["document_sha256"],
        "structural_classification": structural,
        "metadata_sections": sections,
        "explicit_bond_basis": basis,
        "nkd_cohorts": cohorts,
        "account_fees": fees,
        "issues": issues,
    }
