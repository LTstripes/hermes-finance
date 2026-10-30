"""Ephemeral XML + investment-PDF projection inside existing batch preflight.

No ledger/import writer, original persistence, accepted receipt or Close authority.
XML Money remains cash authority; PDF supplies identity/control, never extra cash.
"""

import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

from hermes_finance.domain.instrument_return import (
    CashLeg,
    Coverage,
    Endpoint,
    InstrumentAnalysis,
    InstrumentEvent,
    calculate_economics,
)
from hermes_finance.domain.monthly_return_chain import (
    calculate_interval_return,
    calculate_monthly_return_chain,
)
from hermes_finance.services.mybroker_money_candidates import _narratives
from hermes_finance.services.source_money_classifications import default_classification
from hermes_finance.services.source_monthly_returns import _selected_sources
from hermes_finance.statement_import.extract import extract_pdf_text_layer
from hermes_finance.statement_import.investment_money import parse_investment_money_security
from hermes_finance.statement_import.investment_report import parse_investment_report
from hermes_finance.statement_import.mybroker import NS, PROVIDER, MyBrokerError, digest


def _minor(value):
    with localcontext() as context:
        context.prec = 100
        amount = Decimal(value)
        scaled = amount * 100
        if (
            not amount.is_finite()
            or scaled != scaled.to_integral_value()
            or abs(scaled) > 2**63 - 1
        ):
            raise MyBrokerError("source_return_money_precision_invalid")
        return int(scaled)


def _metric(value, reasons=(), *, method=None, annualized=False):
    return {
        "value": None if value is None else str(value),
        "status": "unavailable" if value is None else ("partial" if reasons else "provisional"),
        "reason_codes": sorted(set(reasons)),
        **({"method": method, "annualized": annualized, "approximate": True} if method else {}),
    }


def _trade_comparison_key(trade):
    if trade["identity"]:
        # Pending and completed sections are different lifecycle observations.
        return digest([trade["identity"], trade["section"]])
    # Comparison only, never a financial identity for an identityless REPO leg.
    if trade.get("repo_observed") and trade.get("ids"):
        return digest(["repo_observation", trade["core"]["source_account"], trade["ids"]])
    return None


def _trade_material(trade):
    return digest(
        {
            key: trade.get(key)
            for key in (
                "section",
                "state",
                "ids",
                "core",
                "settlement_date",
                "depo_settlement_date",
                "settlement_time",
                "bank_commission",
                "accrued_interest",
                "repo_observed",
                "face_value",
            )
        }
    )


def _classification_revision(rows):
    return digest(
        [
            {
                key: value.isoformat() if isinstance(value, (date, datetime)) else value
                for key, value in row.items()
            }
            for row in rows
        ]
    )


def _money(document, payload, *, texts=None):
    texts = list(_narratives(payload)) if texts is None else texts
    if len(texts) != len(document["money"]):
        raise MyBrokerError("source_return_original_money_mismatch")
    result = []
    for raw, (operation, narrative, _) in zip(document["money"], texts):
        kind = default_classification(
            operation,
            narrative,
            raw["kind"],
            raw["amount"],
            source_account=raw["source_account"],
            selected_accounts={raw["source_account"]},
        )
        security = parse_investment_money_security(narrative)
        redemption = None
        if narrative.startswith("полное погашение номинала "):
            redemption = parse_investment_money_security(
                narrative.replace("полное погашение номинала ", "погашение купона ", 1)
            )
        result.append(
            {
                **raw,
                "operation": operation,
                "narrative": narrative,
                "classification": kind,
                "security": security,
                "redemption": redemption,
                "minor": _minor(raw["amount"]),
                "day": date.fromisoformat(raw["date"]),
                "ref": f"{document['document_sha256']}:money:{raw['ordinal']}",
            }
        )
    return result


def _payout_links(documents, money_by_document, report):
    """Fixed registration groups only; never subset-sum or any-date amount search.

    Resolve reg→ISIN by intersection of exact account/kind/day/currency/net
    groups across the supplied originals. Equal-money ambiguity remains unknown.
    """
    pdf = defaultdict(list)
    for row in report.payouts:
        pdf[(row.account, row.kind, row.date, row.currency, row.isin)].append(row)
    links, issues = {}, defaultdict(set)
    for doc in documents:
        account = doc["filename_account"]
        groups = defaultdict(list)
        for row in money_by_document[doc["document_sha256"]]:
            security = row["security"]
            if (
                row["classification"] in {"coupon", "dividend"}
                and security is not None
                and security.kind == row["classification"]
                and row["minor"] > 0
            ):
                groups[
                    (
                        account,
                        security.kind.upper(),
                        row["day"],
                        row["currency"],
                        security.reg_number,
                    )
                ].append(row)
        candidates = {}
        by_reg = defaultdict(list)
        for key, rows in groups.items():
            options = {
                pkey[4]
                for pkey, values in pdf.items()
                if pkey[:4] == key[:4]
                and sum(p.net_kopecks for p in values) == sum(r["minor"] for r in rows)
            }
            candidates[key] = options
            by_reg[(account, key[4])].append(options)
        resolved = {reg: set.intersection(*sets) for reg, sets in by_reg.items()}
        for key, rows in groups.items():
            options = resolved[(account, key[4])]
            if len(options) != 1:
                for isin in candidates[key]:
                    issues[(doc["document_sha256"], isin)].add("payout_identity_ambiguous")
                continue
            isin = next(iter(options))
            # Distinct registrations cannot consume the same PDF cash group.
            competing = [
                k
                for k in groups
                if k != key and k[:4] == key[:4] and isin in resolved[(account, k[4])]
            ]
            if competing:
                issues[(doc["document_sha256"], isin)].add("payout_identity_ambiguous")
                continue
            for row in rows:
                links[row["ref"]] = (isin, key[4])
        for pkey, values in pdf.items():
            if (
                pkey[0] != account
                or not doc["covered_from"] <= pkey[2].isoformat() <= doc["covered_to"]
            ):
                continue
            matched = [
                r
                for r in money_by_document[doc["document_sha256"]]
                if r["ref"] in links
                and links[r["ref"]][0] == pkey[4]
                and (account, r["classification"].upper(), r["day"], r["currency"]) == pkey[:4]
            ]
            if sum(r["minor"] for r in matched) != sum(p.net_kopecks for p in values):
                issues[(doc["document_sha256"], pkey[4])].add("pdf_xml_payout_mismatch")
    return links, issues


def _native(document, payload, *, display_names=None):
    root = ET.fromstring(payload.decode("utf-8-sig"))
    nodes = root.findall("m:Trades/m:Report/m:Tablix2/m:Details_Collection/m:Details", NS)
    trades = [t for t in document["trades"] if t["section"] == "completed"]
    if len(nodes) != len(trades):
        raise MyBrokerError("source_return_native_rows_mismatch")
    names = defaultdict(set)
    primary = defaultdict(list)

    def display_name(isin, value):
        # Optional presentation metadata only. Hashed attribution keys below
        # retain their existing exact lexemes and never consume these labels.
        if display_names is None or not isinstance(value, str):
            return
        value = value.strip()
        if (
            re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin or "")
            and value
            and len(value) <= 256
            and not any(ord(c) < 32 for c in value)
        ):
            display_names.setdefault(isin, set()).add(value)

    for trade, node in zip(trades, nodes):
        if node.get("p_name"):
            names[digest(node.get("p_name"))].add(trade["core"]["isin"])
            display_name(trade["core"]["isin"], node.get("p_name"))
        if trade["ids"]:
            primary[trade["ids"][0]].append(trade)
    position_keys = {(p["source_account"], p["isin"]) for p in document["positions"]}
    for node in root.findall(".//m:Details[@ISIN1]", NS):
        if node.get("ISIN1") and node.get("active_name"):
            names[digest(node.get("active_name"))].add(node.get("ISIN1"))
            if (node.get("acc_code"), node.get("ISIN1")) in position_keys:
                display_name(node.get("ISIN1"), node.get("active_name"))
    cancellations = []
    for node in root.findall("m:Trades3/m:Report/m:Tablix1/m:Details_Collection/m:Details", NS):
        match = re.fullmatch(
            r"[^\r\n]+(?: / |\r?\n)([A-Z]{2}[A-Z0-9]{9}[0-9])", node.get("p_name", "")
        )
        if (
            match
            and node.get("oper_type") == "Перевод"
            and re.fullmatch(r"Аннулирование выпуска [A-Z0-9]+\.", node.get("comment_new", ""))
        ):
            try:
                q = Decimal(node.get("qty", ""))
                day = date.fromisoformat(node.get("settlement_date", "")[:10])
                if q.is_finite() and q < 0:
                    cancellations.append((node.get("acc_code"), match[1], day, q))
            except (ValueError, ArithmeticError):
                pass
    return trades, names, primary, cancellations


def _rates(start, end, v0, v1, flows, reasons=(), *, include_xirr=True):
    interval = calculate_interval_return((start, v0), (end, v1), flows)
    period = (
        calculate_monthly_return_chain([(start, v0), (end, v1)], flows).period
        if include_xirr
        else None
    )
    return {
        "pnl": _metric(interval.growth_kopecks, reasons),
        "modified_dietz": _metric(
            interval.modified_dietz_return,
            tuple(reasons) + interval.reason_codes,
            method="modified_dietz",
        ),
        "xirr_annualized": _metric(
            period.xirr_annualized_return if period is not None else None,
            tuple(reasons) + period.xirr_reason_codes if period is not None else ("not_requested",),
            method="xirr",
            annualized=True,
        ),
        "xirr_period": _metric(
            period.xirr_period_return if period is not None else None,
            tuple(reasons) + period.xirr_reason_codes if period is not None else ("not_requested",),
            method="money_weighted_period",
        ),
    }


def _defer_xirr(interval):
    """Mark omitted optional rates on an owned presentation projection only."""
    for row in (interval, *interval["instruments"]):
        row["xirr_annualized"] = _metric(None, ("not_requested",), method="xirr", annualized=True)
        row["xirr_period"] = _metric(None, ("not_requested",), method="money_weighted_period")
    return interval


def _coverage(reasons):
    """Local dependency sets; unrecognized source faults conservatively affect all.

    A missing valuation never makes an independently reconciled payout unknown.
    Missing identity/cash authority still withholds the complete result.
    """
    categories = ("events", "quantity", "endpoints", "payouts", "costs", "valuation")
    dependencies = {
        "economic_endpoint_unavailable": {"endpoints", "valuation"},
        "zero_quantity_value_conflict": {"quantity", "endpoints", "valuation"},
        "quantity_bridge_mismatch": {"quantity", "costs"},
        "pdf_xml_position_mismatch": {"quantity", "endpoints", "valuation"},
        "pdf_position_invalid": {"quantity", "endpoints", "valuation"},
        "pdf_position_date_missing": {"endpoints", "valuation"},
        "pdf_position_date_invalid": {"endpoints", "valuation"},
        "pdf_account_summary_invalid": {"valuation"},
        "pdf_payout_row_invalid": {"payouts"},
        "payout_identity_ambiguous": {"payouts"},
        "pdf_xml_payout_mismatch": {"payouts"},
        "unresolved_account_payout_attribution": {"payouts"},
        "native_commission_unavailable": {"events", "costs"},
        "native_money_cash_bridge_mismatch": {"events", "costs"},
        "native_money_role_ambiguous": {"events", "costs"},
        "native_settlement_unavailable": {"events", "quantity", "costs"},
        "native_settlement_outside_period": {"events", "quantity", "costs"},
        "native_account_conflict": {"events", "quantity", "costs"},
        "repo_position_open_at_boundary": {"events", "quantity", "costs"},
    }
    return {
        category: Coverage(
            not (
                codes := tuple(
                    sorted(r for r in reasons if category in dependencies.get(r, categories))
                )
            ),
            codes,
        )
        for category in categories
    }


def _unresolved_movements(payload, native_account, matched_cancellations):
    """Net-zero custody movements still need dated/value/flow meaning.

    An exact, cash-corroborated cancellation is recognized separately. A service
    connection status is metadata, not a movement. No legacy blocker is cleared.
    """
    root = ET.fromstring(payload.decode("utf-8-sig"))
    remaining = Counter(matched_cancellations)
    unresolved = []
    for outer in ("Trades3", "Trades4"):
        wrapper = root.find(f"m:{outer}", NS)
        report = wrapper.find("m:Report", NS) if wrapper is not None else None
        if wrapper is None or list(wrapper) != [report] or (wrapper.text or "").strip():
            unresolved.append({"isin": None, "reason": "unresolved_native_movement_wrapper"})
    for node in root.findall("m:Trades3/m:Report//m:Details", NS):
        observed_account = node.get("acc_code")
        if (
            observed_account
            and re.fullmatch(r"[0-9]{1,32}-[0-9]{3}", observed_account)
            and observed_account != native_account
        ):
            continue
        match = re.fullmatch(
            r"[^\r\n]+(?: / |\r?\n)([A-Z]{2}[A-Z0-9]{9}[0-9])", node.get("p_name", "")
        )
        key = None
        try:
            if match:
                quantity = Decimal(node.get("qty", ""))
                if not quantity.is_finite():
                    raise ValueError
                key = (
                    node.get("acc_code"),
                    match[1],
                    date.fromisoformat(node.get("settlement_date", "")[:10]),
                    quantity,
                )
        except (ValueError, ArithmeticError):
            pass
        if (
            key
            and remaining[key]
            and node.get("oper_type") == "Перевод"
            and re.fullmatch(r"Аннулирование выпуска [A-Z0-9]+\.", node.get("comment_new", ""))
        ):
            remaining[key] -= 1
        else:
            unresolved.append(
                {
                    "isin": match[1] if match else None,
                    "reason": "unresolved_native_security_movement",
                }
            )
    for node in root.findall("m:Trades4/m:Report//m:Details", NS):
        # Known connection timestamps contain no dated security/cash transaction.
        if (
            set(node.attrib) == {"sys_start_time", "sys_end_time"}
            and not list(node)
            and not (node.text or "").strip()
        ):
            continue
        unresolved.append({"isin": None, "reason": "unresolved_native_auxiliary_row"})
    native_transfers = root.find("m:Trades3/m:Report", NS)
    if native_transfers is not None and any(
        n.tag
        not in {
            f"{{MyBroker}}{name}" for name in ("Report", "Tablix1", "Details_Collection", "Details")
        }
        for n in native_transfers.iter()
    ):
        unresolved.append({"isin": None, "reason": "unresolved_native_movement_structure"})
    auxiliary = root.find("m:Trades4/m:Report", NS)
    if auxiliary is not None and any(
        n.tag
        not in {
            f"{{MyBroker}}{name}" for name in ("Report", "Tablix1", "Details_Collection", "Details")
        }
        for n in auxiliary.iter()
    ):
        unresolved.append({"isin": None, "reason": "unresolved_native_auxiliary_structure"})
    if "unknown_section" in parse_source_blockers(root):
        unresolved.append({"isin": None, "reason": "unknown_native_section"})
    return unresolved


def parse_source_blockers(root):
    from hermes_finance.statement_import.mybroker import SECTIONS

    return (
        {"unknown_section"}
        if any(child.tag not in {f"{{MyBroker}}{name}" for name in SECTIONS} for child in root)
        else set()
    )


def _interval(
    document,
    payload,
    report,
    money,
    links,
    link_issues,
    from_zero,
    *,
    native_evidence=None,
    analyses=None,
    requested_isin=None,
    include_xirr=True,
):
    account = document["filename_account"]
    native_account = {r["source_account"] for r in document["money"] + document["positions"]}
    native_account.update(t["core"]["source_account"] for t in document["trades"])
    if len(native_account) != 1:
        raise MyBrokerError("source_return_account_ambiguous")
    native_account = next(iter(native_account))
    if native_account not in {account, f"{account}-000"}:
        raise MyBrokerError("source_return_filename_native_account_conflict")
    start = date.fromisoformat(document["covered_from"]) - timedelta(days=1)
    end = date.fromisoformat(document["covered_to"])
    if native_evidence is None:
        trades, names, primary, cancellations = _native(document, payload)
    else:
        trades = [t for t in document["trades"] if t["section"] == "completed"]
        names = {k: set(v) for k, v in native_evidence["names"].items()}
        primary = defaultdict(list)
        for trade in trades:
            if trade["ids"]:
                primary[trade["ids"][0]].append(trade)
        cancellations = [
            (a, i, date.fromisoformat(d), Decimal(q))
            for a, i, d, q in native_evidence["cancellations"]
        ]
    qdelta = defaultdict(Decimal)
    repo_quantity = defaultdict(Decimal)
    expected = defaultdict(int)
    repo_groups = set()
    issues = defaultdict(set)
    for t in trades:
        isin = t["core"]["isin"]
        if (
            t["state"] != "settled"
            or not t.get("settlement_date")
            or not t.get("depo_settlement_date")
        ):
            issues[isin].add("native_settlement_unavailable")
            continue
        if t["core"]["source_account"] != native_account:
            issues[isin].add("native_account_conflict")
            continue
        q = Decimal(t["core"]["quantity"])
        if not (
            start < date.fromisoformat(t["settlement_date"]) <= end
            and start < date.fromisoformat(t["depo_settlement_date"]) <= end
        ):
            issues[isin].add("native_settlement_outside_period")
            continue
        qdelta[isin] += q
        day = date.fromisoformat(t["settlement_date"])
        key = (isin, day, t["core"]["currency"], bool(t.get("repo_observed")))
        if t.get("bank_commission") is None:
            issues[isin].add("native_commission_unavailable")
        expected[key] += (-1 if q > 0 else 1) * abs(_minor(t["core"]["trade_amount"])) - abs(
            _minor(t.get("bank_commission") or "0")
        )
        if t.get("repo_observed"):
            repo_groups.add(key)
            repo_quantity[isin] += q
    for isin, quantity in repo_quantity.items():
        if quantity != 0:
            issues[isin].add("repo_position_open_at_boundary")
    native_money = defaultdict(list)
    events = defaultdict(list)
    only = []
    external = []
    unlinked = []
    redemptions = defaultdict(Decimal)
    matched_cancellations = []
    reg_to_isin = defaultdict(set)
    for row in money:
        if row["ref"] in links:
            reg_to_isin[links[row["ref"]][1]].add(links[row["ref"]][0])
    for row in money:
        amount, day, currency = row["minor"], row["day"], row["currency"]
        if not start < day <= end:
            raise MyBrokerError("source_return_money_outside_period")
        kind = row["classification"]
        isin = None
        event_kind = None
        if row["source_account"] != native_account:
            raise MyBrokerError("source_return_money_account_conflict")
        if currency != "RUB":
            unlinked.append(row)
            continue
        if kind in {"external_deposit", "external_withdrawal"}:
            external.append((day, amount, "confirmed"))
            continue
        if kind in {"coupon", "dividend"}:
            if row["ref"] in links:
                isin = links[row["ref"]][0]
                event_kind = kind.upper()
            else:
                unlinked.append(row)
                continue
        elif row["redemption"]:
            options = reg_to_isin[row["redemption"].reg_number]
            candidates = [
                c
                for c in cancellations
                if c[0] == native_account and c[2] == day and c[1] in options
            ]
            if len(candidates) == 1 and amount > 0:
                _, isin, _, q = candidates[0]
                redemptions[isin] += q
                matched_cancellations.append(candidates[0])
                event_kind = "REDEMPTION"
            else:
                unlinked.append(row)
                continue
        elif kind in {"trade_settlement", "fee"}:
            token = row.get("native_token", row.get("primary_id"))
            match = re.fullmatch(
                r"(?:Расчеты|Комиссия) по сделке ([0-9]{1,128}|B[0-9]{1,127})", row["operation"]
            )
            if token is None and match:
                token = match[1]
            options = {
                t["core"]["isin"]
                for t in primary.get(token, [])
                if t.get("settlement_date") == row["date"]
                and t["core"]["source_account"] == native_account
            }
            if token is not None and len(options) == 1:
                isin = next(iter(options))
            elif row["operation"].casefold().strip() == "нкд по сделке":
                label = re.fullmatch(r"[cс] ([^\r\n]+)", row["narrative"], re.IGNORECASE)
                values = names.get(digest(label[1]), set()) if label else set()
                if len(values) == 1:
                    isin = next(iter(values))
            if isin:
                roles = (
                    {
                        bool(t.get("repo_observed"))
                        for t in primary.get(token, [])
                        if t["core"]["isin"] == isin and t.get("settlement_date") == row["date"]
                    }
                    if token
                    else {key[3] for key in expected if key[:3] == (isin, day, currency)}
                )
                if len(roles) == 1:
                    native_money[(isin, day, currency, next(iter(roles)))].append(row)
                    continue
                issues[isin].add("native_money_role_ambiguous")
            if kind == "trade_settlement":
                unlinked.append(row)
                continue
            only.append(
                {"kind": "account_fee", "amount_kopecks": str(amount), "reference": row["ref"]}
            )
            continue
        elif kind == "tax":
            only.append(
                {"kind": "account_tax", "amount_kopecks": str(amount), "reference": row["ref"]}
            )
            continue
        elif (
            kind == "unknown"
            and row["operation"] == "Перевод"
            and re.fullmatch(
                r"Компенсация утраченных дивидендов по акциям [A-Z0-9_]+ дата фиксации реестра [0-9/]+\.",
                row["narrative"],
            )
        ):
            only.append(
                {
                    "kind": "unallocated_compensation",
                    "amount_kopecks": str(amount),
                    "reference": row["ref"],
                }
            )
            continue
        else:
            unlinked.append(row)
            continue
        events[isin].append(
            InstrumentEvent(
                event_key=row["ref"],
                provider=PROVIDER,
                native_source_account=native_account,
                isin=isin,
                kind=event_kind,
                source_references=(row["ref"],),
                event_date=day,
                cash_legs=(
                    CashLeg(event_kind.lower(), day, amount, -amount, (row["ref"],), row["ref"]),
                ),
                attribution_basis="xml_pdf_original_bound",
                effective_isin=isin,
                net_payout_kopecks=amount if event_kind in {"COUPON", "DIVIDEND"} else None,
                classification=kind,
                classification_origin="xml_pdf_original_bound",
                classification_status="confirmed",
            )
        )
    for key in sorted(set(expected) | set(native_money)):
        isin, day, currency, _ = key
        rows = native_money[key]
        amount = sum(r["minor"] for r in rows)
        if currency != "RUB" or key not in expected or amount != expected[key]:
            issues[isin].add("native_money_cash_bridge_mismatch")
        if key in repo_groups:
            only.append(
                {
                    "kind": "repo_financing",
                    "isin": isin,
                    "amount_kopecks": str(amount),
                    "references": [r["ref"] for r in rows],
                }
            )
            continue
        for row in rows:
            event_kind = (
                "FEE" if row["classification"] == "fee" else ("BUY" if row["minor"] < 0 else "SELL")
            )
            events[isin].append(
                InstrumentEvent(
                    event_key=row["ref"],
                    provider=PROVIDER,
                    native_source_account=native_account,
                    isin=isin,
                    kind=event_kind,
                    source_references=(row["ref"],),
                    event_date=day,
                    cash_legs=(
                        CashLeg(
                            "native_money",
                            day,
                            row["minor"],
                            -row["minor"],
                            (row["ref"],),
                            row["ref"],
                        ),
                    ),
                    attribution_basis="native_money_group_bridge",
                    effective_isin=isin,
                    classification=row["classification"],
                    classification_origin="native_money_group_bridge",
                    classification_status="confirmed",
                )
            )
    positions = {p["isin"]: p for p in document["positions"]}
    if len(positions) != len(document["positions"]):
        raise MyBrokerError("source_return_duplicate_position")
    cash = document["rub_money"]
    if len(cash) != 1:
        raise MyBrokerError("source_return_rub_cash_unavailable")
    if cash[0]["source_account"] != native_account or any(
        cash[0].get(key) is None for key in ("beginning_amount", "ending_amount")
    ):
        raise MyBrokerError("source_return_rub_cash_incomplete")
    inception = (
        from_zero
        and Decimal(cash[0]["beginning_amount"]) == 0
        and all(Decimal(p["beginning_actual_quantity"] or "NaN") == 0 for p in positions.values())
    )
    if from_zero and not inception:
        raise MyBrokerError("source_return_zero_start_contradiction")
    instruments = []
    if native_evidence is None:
        movements = _unresolved_movements(payload, native_account, matched_cancellations)
    else:
        movements = list(native_evidence["unresolved"])
        remaining = Counter(cancellations) - Counter(matched_cancellations)
        movements.extend(
            {"isin": c[1], "reason": "unresolved_native_security_movement"}
            for c, n in remaining.items()
            for _ in range(n)
        )
    unresolved_payouts = any(r["classification"] in {"coupon", "dividend"} for r in unlinked)
    advisory_reasons = (
        ("source_sections_not_financially_accepted",) if document["syntax_blockers"] else ()
    )
    v0total = _minor(cash[0]["beginning_amount"])
    v1total = _minor(cash[0]["ending_amount"])
    for isin in sorted(set(positions) | set(qdelta) | set(events) | set(redemptions)):
        p = positions.get(isin)
        q0 = q1 = None
        v0 = v1 = None
        why = set(issues[isin]) | set(link_issues.get((document["document_sha256"], isin), ()))
        why.update(code for a, code in report.issues if a == account)
        why.update(code for a, i, code in report.instrument_issues if (a, i) == (account, isin))
        if unresolved_payouts:
            why.add("unresolved_account_payout_attribution")
        if any(r["classification"] not in {"coupon", "dividend"} for r in unlinked):
            why.add("unresolved_account_cash_attribution")
        why.update(m["reason"] for m in movements if m["isin"] in (None, isin))
        if p:
            q0 = (
                Decimal(p["beginning_actual_quantity"])
                if p.get("beginning_actual_quantity") is not None
                else None
            )
            q1 = Decimal(p["actual_quantity"]) if p.get("actual_quantity") is not None else None
            v0 = (
                _minor(p["beginning_value"])
                if p.get("beginning_value") is not None
                else (0 if q0 == 0 else None)
            )
            v1 = (
                _minor(p["ending_value"])
                if p.get("ending_value") is not None
                else (0 if q1 == 0 else None)
            )
            if (q0 == 0 and v0 not in (None, 0)) or (q1 == 0 and v1 not in (None, 0)):
                why.add("zero_quantity_value_conflict")
            observed = report.positions.get((account, isin))
            if observed is None or Decimal(observed[0]) != q1 or observed[1] != v1:
                why.add("pdf_xml_position_mismatch")
        elif inception and (account, isin) in report.closed_isins:
            q0 = Decimal(0)
            q1 = qdelta[isin] + redemptions[isin]
            if q1 == 0:
                v0 = v1 = 0
        elif inception and isin not in events and qdelta[isin] == 0:
            # A fully paired REPO's financing cash is disclosed at account scope.
            q0 = q1 = Decimal(0)
            v0 = v1 = 0
        if q0 is None or q1 is None or q0 + qdelta[isin] + redemptions[isin] != q1:
            why.add("quantity_bridge_mismatch")
        if v0 is None or v1 is None:
            why.add("economic_endpoint_unavailable")
        if p:
            v0total = None if v0total is None or v0 is None else v0total + v0
            v1total = None if v1total is None or v1 is None else v1total + v1
        coverage = _coverage(why)
        opening = Endpoint(start, q0, v0, v0, None, "dirty")
        closing = Endpoint(end, q1, v1, v1, None, "dirty")
        components, pnl, known, dietz, estimate = calculate_economics(
            opening, closing, events[isin], coverage
        )
        # All source/event/quantity/cash checks and account valuation operands
        # above remain complete. Only the unused instrument projection and its
        # expensive XIRR are omitted for an exact instrument detail request.
        if requested_isin is not None and isin != requested_isin:
            continue
        flows = [
            (leg.date, leg.instrument_flow_kopecks, "confirmed")
            for e in events[isin]
            for leg in e.cash_legs
        ]
        rates = _rates(
            start, end, v0, v1, flows, tuple(why) + advisory_reasons, include_xirr=include_xirr
        )
        if why:
            for key in rates:
                rates[key]["value"] = None
                rates[key]["status"] = "unavailable"
        if analyses is not None:
            reasons = tuple(sorted(why)) + advisory_reasons

            def qualified(metric):
                return replace(
                    metric,
                    status="provisional"
                    if metric.value is not None
                    and advisory_reasons
                    and metric.status == "supported"
                    else metric.status,
                    reason_codes=tuple(sorted(set(metric.reason_codes + advisory_reasons))),
                )

            analyses[isin] = InstrumentAnalysis(
                opening_date=start,
                closing_date=end,
                history_start=start + timedelta(days=1),
                history_end=end,
                history_complete_since_acquisition=inception,
                events=tuple(events[isin]),
                opening=opening,
                closing=closing,
                components={k: qualified(v) for k, v in components.items()},
                pnl=qualified(pnl),
                known_subtotal=known,
                modified_dietz=qualified(dietz),
                coverage=coverage,
                source_references=(),
                reason_codes=reasons,
                assumptions=("source_only_xml_pdf",),
                statement_estimate=estimate,
            )
        instruments.append(
            {
                "isin": isin,
                "opening_quantity": None if q0 is None else str(q0),
                "closing_quantity": None if q1 is None else str(q1),
                "opening_kopecks": None if v0 is None else str(v0),
                "closing_kopecks": None if v1 is None else str(v1),
                "result_scope": "linked_instrument_cash_and_valuation; account-wide items separate",
                "pnl": _metric(pnl.value, tuple(why) + advisory_reasons),
                "known_subtotal": {
                    **_metric(known.value, tuple(why) + advisory_reasons),
                    "status": "partial" if known.value is not None else "unavailable",
                },
                "modified_dietz": _metric(
                    dietz.value,
                    tuple(why) + dietz.reason_codes + advisory_reasons,
                    method="modified_dietz",
                ),
                "xirr_annualized": rates["xirr_annualized"],
                "xirr_period": rates["xirr_period"],
                "components": {k: _metric(v.value, v.reason_codes) for k, v in components.items()},
                "event_count": len(events[isin]),
                "reason_codes": sorted(why),
            }
        )
    account_reasons = {code for a, code in report.issues if a == account}
    account_reasons.update(code for a, _, code in report.instrument_issues if a == account)
    account_reasons.update(advisory_reasons)
    if any(q != 0 for q in repo_quantity.values()):
        account_reasons.add("repo_position_open_at_boundary")
    if account not in report.closing:
        account_reasons.add("pdf_account_summary_missing")
    if account not in report.payout_accounts:
        account_reasons.add("pdf_actual_payout_section_missing")
    if any(r["classification"] not in {"coupon", "dividend"} for r in unlinked):
        external.extend(
            (r["day"], r["minor"] if r["currency"] == "RUB" else 0, "unknown")
            for r in unlinked
            if r["classification"] not in {"coupon", "dividend"}
        )
        account_reasons.add("unclassified_money")
    if any(r["currency"] != "RUB" for r in unlinked):
        external.append((end, 0, "unknown"))
        account_reasons.add("non_rub_money_valuation_unknown")
    rates = _rates(
        start, end, v0total, v1total, external, account_reasons, include_xirr=include_xirr
    )
    known_subtotal = {
        **rates["pnl"],
        "status": "partial" if rates["pnl"]["value"] is not None else "unavailable",
    }
    if movements:
        account_reasons.update(m["reason"] for m in movements)
        known_subtotal["reason_codes"] = sorted(account_reasons)
        for metric in rates.values():
            metric.update(value=None, status="unavailable", reason_codes=sorted(account_reasons))
    cash_delta = (
        _minor(cash[0]["ending_amount"])
        - _minor(cash[0]["beginning_amount"])
        - sum(r["minor"] for r in money if r["currency"] == "RUB")
    )
    pdf_delta = (
        None
        if v1total is None or account not in report.closing
        else v1total - report.closing[account]
    )
    pnl_value = rates["pnl"]["value"]
    reported = report.reported_pnl.get(account)
    pnl_delta = (
        None
        if pnl_value is None
        or reported is None
        or not (inception or date.fromisoformat(document["covered_from"]) == report.start)
        else int(pnl_value) - reported
    )
    if pdf_delta not in (None, 0) or pnl_delta not in (None, 0) or cash_delta not in (None, 0):
        account_reasons.add("source_control_mismatch")
    for m in rates.values():
        if m["value"] is not None and account_reasons:
            m["status"] = "partial"
            m["reason_codes"] = sorted(account_reasons)
    linked_rows = sum(r["ref"] in links for r in money)
    result = {
        "source_account": account,
        "source_sha256": document["document_sha256"],
        "opening_date": str(start),
        "closing_date": str(end),
        "period_kind": "monthly"
        if start.day in {28, 29, 30, 31} and (start + timedelta(days=1)).month == end.month
        else "historical_interval",
        "history_from_zero": inception,
        "opening_kopecks": None if v0total is None else str(v0total),
        "closing_kopecks": None if v1total is None else str(v1total),
        "external_flows": [
            {"date": str(d), "amount_kopecks": str(a), "status": status}
            for d, a, status in external
        ],
        "contributions_kopecks": None
        if any(s == "unknown" for _, _, s in external)
        else str(sum(a for _, a, _ in external if a > 0)),
        "withdrawals_kopecks": None
        if any(s == "unknown" for _, _, s in external)
        else str(-sum(a for _, a, _ in external if a < 0)),
        "income_reason_codes": {
            name: sorted(
                set(advisory_reasons)
                | (
                    {"unclassified_money"}
                    if any(r["classification"] not in {"coupon", "dividend"} for r in unlinked)
                    else set()
                )
            )
            for name in ("coupons", "dividends")
        },
        "coupons_kopecks": str(
            sum(
                r["minor"]
                for r in money
                if r["classification"] == "coupon" and r["currency"] == "RUB"
            )
        )
        if not any(r["currency"] != "RUB" and r["classification"] == "coupon" for r in money)
        else None,
        "dividends_kopecks": str(
            sum(
                r["minor"]
                for r in money
                if r["classification"] == "dividend" and r["currency"] == "RUB"
            )
        )
        if not any(r["currency"] != "RUB" and r["classification"] == "dividend" for r in money)
        else None,
        **rates,
        "known_subtotal": known_subtotal,
        "unresolved_movements": movements,
        "instruments": instruments,
        "account_only": only,
        "exceptions": [
            {
                "reference": r["ref"],
                "date": r["date"],
                "currency": r["currency"],
                "amount_kopecks": str(r["minor"]) if r["currency"] == "RUB" else None,
                "classification": r["classification"],
                "registration": r["security"].reg_number if r["security"] else None,
            }
            for r in unlinked
        ],
        "unallocated_payouts": [
            {
                "reference": r["ref"],
                "amount_kopecks": str(r["minor"]),
                "reason": "payout_identity_unresolved",
            }
            for r in unlinked
            if r["classification"] in {"coupon", "dividend"}
        ],
        "reconciliation": {
            "cash_delta_kopecks": None if cash_delta is None else str(cash_delta),
            "pdf_closing_delta_kopecks": None if pdf_delta is None else str(pdf_delta),
            "pdf_pnl_delta_kopecks": None if pnl_delta is None else str(pnl_delta),
            "xml_payout_occurrences": sum(
                r["classification"] in {"coupon", "dividend"} for r in money
            ),
            "linked_payout_occurrences": linked_rows,
            "native_trades": len(trades),
            "repo_legs": sum(bool(t.get("repo_observed")) for t in trades),
        },
        "source_advisories": document["syntax_blockers"],
        "reason_codes": sorted(account_reasons),
    }
    return result if include_xirr else _defer_xirr(result)


def preview_source_reports(session, entries, originals, income_report, *, history_from_zero=False):
    """Use exact uploads and current saved-source views; never stage or update them."""
    documents = [e["document"] for e in entries]
    accounts = {d["filename_account"] for d in documents}
    if None in accounts:
        raise MyBrokerError("source_return_account_missing")
    report = parse_investment_report(extract_pdf_text_layer(income_report), accounts)
    import hashlib

    payloads = {hashlib.sha256(raw).hexdigest(): raw for _, raw in originals}
    money = {d["document_sha256"]: _money(d, payloads[d["document_sha256"]]) for d in documents}
    links, issues = _payout_links(documents, money, report)
    intervals = []
    comparison = []
    dependencies = []
    for account in sorted(accounts):
        selected, _ = _selected_sources(session, account)
        saved_trades = defaultdict(set)
        saved_money = defaultdict(int)
        for original, view, error in selected:
            if error:
                comparison.append({"source_account": account, "kind": "saved_source_unavailable"})
                continue
            dependencies.append(
                (
                    original.id,
                    view["head_seq"],
                    view["manifest_digest"],
                    _classification_revision(view["money_classifications"]),
                    digest(view["document"]),
                )
            )
            for trade in view["document"]["trades"]:
                key = _trade_comparison_key(trade)
                if key:
                    saved_trades[key].add(_trade_material(trade))
            per_source = Counter(
                (str(r["date"]), r["amount_kopecks"], r["currency"], r["operation"], r["narrative"])
                for r in view["money_classifications"]
            )
            for key, count in per_source.items():
                saved_money[key] = max(saved_money[key], count)
        for d in documents:
            if d["filename_account"] != account:
                continue
            if "period_inferred_from_content" in d.get("warnings", []):
                raise MyBrokerError("source_return_declared_period_required")
            if report.start > date.fromisoformat(
                d["covered_from"]
            ) or report.end < date.fromisoformat(d["covered_to"]):
                raise MyBrokerError("investment_pdf_scope_incomplete")
            if report.end != date.fromisoformat(d["covered_to"]):
                raise MyBrokerError("investment_pdf_endpoint_scope_mismatch")
            stats = Counter()
            conflicts = []
            for t in d["trades"]:
                key = _trade_comparison_key(t)
                known = saved_trades.get(key, set()) if key else set()
                stats[
                    "conflicting_native_trades"
                    if known - {_trade_material(t)}
                    else "repeated_native_trades"
                    if known
                    else "new_native_trades"
                ] += 1
                if known - {_trade_material(t)}:
                    conflicts.append(
                        {
                            "kind": "native_trade_material_conflict",
                            "isin": t["core"]["isin"],
                            "identity": key,
                            "settlement_date": t.get("settlement_date"),
                        }
                    )
            incoming = Counter(
                (r["date"], r["minor"], r["currency"], r["operation"], r["narrative"])
                for r in money[d["document_sha256"]]
            )
            stats["repeated_money_occurrences"] = sum(
                min(n, saved_money[key]) for key, n in incoming.items()
            )
            stats["unmatched_money_occurrences"] = sum(
                max(0, n - saved_money[key]) for key, n in incoming.items()
            )
            for key in ("new_native_trades", "repeated_native_trades", "conflicting_native_trades"):
                stats.setdefault(key, 0)
            comparison.append(
                {
                    "source_account": account,
                    "source_sha256": d["document_sha256"],
                    **stats,
                    "conflicts": conflicts,
                    "closed_financial_rows_replaced": 0,
                }
            )
            intervals.append(
                _interval(
                    d,
                    payloads[d["document_sha256"]],
                    report,
                    money[d["document_sha256"]],
                    links,
                    issues,
                    history_from_zero,
                )
            )
    from hermes_finance.services.source_investment_proofs import prepare

    persistence = prepare(
        session,
        sorted(documents, key=lambda d: d["filename_account"]),
        payloads,
        {hashlib.sha256(raw).hexdigest(): name for name, raw in originals},
        report,
        intervals,
        comparison,
        history_from_zero,
    )
    return {
        "contract": "xml-pdf-source-return-preview-v1",
        "persistence": persistence,
        "financial_authority": "none",
        "financial_apply_available": False,
        "close_available": False,
        "scope": "uploaded_xml_accounts_only",
        "source_accounts": sorted(accounts),
        "pdf_sha256": report.sha256,
        "pdf_period": {"covered_from": str(report.start), "covered_to": str(report.end)},
        "pdf_payout_rows": len(report.payouts),
        "context_fingerprint": digest(
            [
                sorted((name, hashlib.sha256(raw).hexdigest()) for name, raw in originals),
                report.sha256,
                history_from_zero,
                sorted(dependencies),
            ]
        ),
        "comparison": comparison,
        "intervals": intervals,
        "actual_payouts_not_forecast": True,
        "pdf_cash_added": False,
        "history_requires_old_month_close": False,
    }
