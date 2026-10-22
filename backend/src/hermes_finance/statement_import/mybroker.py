"""Bounded MyBroker S1 syntax with endpoint evidence. No financial writes.

The constants come from the sanitized Integrator manifests for issues #708 and
#716. Positions expose the accepted boundary quantities/values and the RUB
currency row; only normalized source facts are returned, and names/comments/raw
XML are discarded. No class inference, payout or bond arithmetic.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

PROVIDER = "alfa_mybroker"
PARSER = "mybroker-s1-v2"
# Optional, bounded grammar extension. Absence in an accepted receipt means the
# frozen comment-only grammar, not permission to upgrade its saved occurrences.
MONEY_LINKAGE = "mybroker-money-linkage-v1"
LINKAGE = re.compile(r"(Расчеты|Комиссия) по сделке ([0-9]{1,128})")
NS = {"m": "MyBroker"}
# Accepted #716 currency-row conjunction; only the exact row-level placement is
# accepted, and anything else stays a visible fail-closed blocker.
CURRENCY_TYPE = "Валюта"
CURRENCY_NAME = "RUB"
SCHEMA = (
    "MyBroker http://reporting.alfadirect.ru/ReportServer?"
    "%2FCabinet%2FRelease%2FMyBroker&rs%3AFormat=XML&rc%3ASchema=True"
)
SECTIONS = {
    "Positions": "1_Positions",
    "Trades": "2_Trades",
    "Trades2": "3_BrokerMoneyMove",
    "Trades3": "4_Transfers",
    "Trades4": "5_UFSR",
}
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
FILENAME = re.compile(
    r"Брокерский (?P<account>\d+) \((?P<start>\d{2}\.\d{2}\.\d{2})-"
    r"(?P<end>\d{2}\.\d{2}\.\d{2})\)\.xml",
    re.ASCII,
)


class MyBrokerError(ValueError):
    """Sanitized, stable error code; never include source values in errors."""


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def frozen_source_shape(fresh: dict, stored: dict) -> dict:
    """Reproduce only the optional nominal keys already present in frozen v2 facts.

    Exact-original checks remain the caller's responsibility. Missing saved keys
    mean the old grammar, never permission to promote a reattached nominal.
    Legacy empty-as-None nominal remains frozen as unknown. All other fields,
    row counts and recorded nominal values still must match.
    """
    if fresh.get("parser") != PARSER or stored.get("parser") != PARSER:
        return fresh
    result = dict(fresh)
    for section in ("positions", "trades"):
        rows, old_rows = fresh.get(section, []), stored.get(section, [])
        if len(rows) == len(old_rows):
            result[section] = [
                {key: value for key, value in row.items() if key != "face_value" or key in old}
                for row, old in zip(rows, old_rows, strict=True)
            ]
            for row, old in zip(result[section], old_rows, strict=True):
                # Older parsing collapsed empty nominal to the invalid marker.
                # Reattachment must preserve that frozen unknown, not promote it.
                if row.get("face_value") == "" and old.get("face_value") is None:
                    row["face_value"] = None
    return result


def lines(value: str | None) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def single(value: str | None, *, optional: bool = False) -> str | None:
    values = list(dict.fromkeys(lines(value)))
    if not values and optional:
        return None
    if len(values) != 1 or len(values[0]) > 128:
        raise MyBrokerError("ambiguous_or_missing_field")
    return values[0]


def decimal(value: str | None, *, optional: bool = False) -> str | None:
    token = single(value, optional=optional)
    if token is None:
        return None
    if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", token) or len(token) > 48:
        raise MyBrokerError("invalid_decimal")
    number = Decimal(token)
    if not number:
        return "0"
    normalized = format(number, "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def day(value: str | None, *, optional: bool = False) -> str | None:
    token = single(value, optional=optional)
    if token is None:
        return None
    if not re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", token):
        raise MyBrokerError("invalid_date")
    try:
        return datetime.strptime(token, "%d.%m.%Y").date().isoformat()
    except ValueError:
        raise MyBrokerError("invalid_date") from None


def timestamp(value: str | None, *, iso: bool = False, optional: bool = False) -> str | None:
    token = single(value, optional=optional)
    if token is None:
        return None
    pattern = (
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        if iso
        else r"[0-9]{1,2}\.[0-9]{2}\.[0-9]{4} [0-9]{1,2}:[0-9]{2}:[0-9]{2}"
    )
    if not re.fullmatch(pattern, token):
        raise MyBrokerError("invalid_timestamp")
    try:
        return datetime.strptime(
            token, "%Y-%m-%dT%H:%M:%S" if iso else "%d.%m.%Y %H:%M:%S"
        ).isoformat()
    except ValueError:
        raise MyBrokerError("invalid_timestamp") from None


def _ids(value: str | None) -> list[str]:
    values = lines(value)
    if len(values) < 2:
        if all(re.fullmatch(r"[0-9]{1,128}", item) for item in values):
            return values
    # Duplicate complete two-part values may occur, but roles are not deduplicated.
    if len(values) >= 2 and len(values) % 2 == 0:
        pair = values[:2]
        if all(values[i : i + 2] == pair for i in range(0, len(values), 2)):
            if all(re.fullmatch(r"[0-9]{1,128}", item) for item in pair):
                return pair
    raise MyBrokerError("trade_ids_ambiguous")


def _face_value_fields(row: ET.Element, *, pending: bool = False) -> dict:
    """Return optional source nominal facts without inventing a default.

    The result is one of:
    - ``{}``: no recognized nominal attribute is present; legacy rows keep
      their frozen normalized payloads.
    - ``{"face_value": ""}``: a nominal attribute is present but every value
      is empty, i.e. the row has no usable nominal.
    - ``{"face_value": None}``: the nominal is invalid or the aliases
      conflict; it stays unknown and is never replaced by a fallback.
    - ``{"face_value": <normalized string>}``: the single agreeing nominal.
    """
    names = ("face_value", "nominal", "nominal_value")
    if pending:
        names += tuple(name + "2" for name in names)
    tokens = [row.get(name) for name in names if name in row.attrib]
    if not tokens:
        return {}
    try:
        values = {decimal(token, optional=True) for token in tokens}
    except MyBrokerError:
        return {"face_value": None}
    # Preserve empty separately from invalid/conflicting nominal so a
    # provisional reader may disclose an assumption without accepting bad data.
    if values == {None}:
        return {"face_value": ""}
    return {"face_value": next(iter(values)) if len(values) == 1 else None}


def _trade(row: ET.Element, *, pending: bool, ordinal: int) -> dict:
    names = {
        "ids": "trade_no1" if pending else "trade_no",
        "account": "acc_code2" if pending else "acc_code",
        "isin": "isin_reg1" if pending else "isin_reg",
        "time": "db_time2" if pending else "db_time",
        "qty": "qty2" if pending else "qty",
        "price": "Price2" if pending else "Price",
        "amount": "summ_trade2" if pending else "summ_trade",
        "nkd": "summ_nkd2" if pending else "summ_nkd",
        "currency": "curr_calc2" if pending else "curr_calc",
        "commission": "bank_tax2" if pending else "bank_tax",
        "settlement": "save_settlement_date3" if pending else "save_settlement_date",
        "depo": "save_depo_settlement_date3" if pending else "save_depo_settlement_date",
        "settlement_time": "settlement_time2" if pending else "settlement_time",
        "repo": "repo_no1" if pending else "repo_no",
    }

    def get(key: str) -> str | None:
        return row.get(names[key])

    # #736 sanitized manifest: only a completed one-part B ID with an explicit
    # REPO-leg marker and a distinct, unambiguous B partner is accepted here.
    # The partner is a guard, never the missing second native economic ID.
    source_ids = lines(get("ids"))
    if not pending and len(source_ids) == 1 and re.fullmatch(r"B[0-9]{1,127}", source_ids[0]):
        partners = lines(get("repo"))
        if (
            len(partners) != 1
            or not re.fullmatch(r"B[0-9]{1,127}", partners[0])
            or partners[0] == source_ids[0]
            or row.get("comment") not in {"репо ч.1", "репо ч.2"}
        ):
            raise MyBrokerError("trade_ids_ambiguous")
        ids = source_ids
    else:
        ids = _ids(get("ids"))
    account = single(get("account"))
    core = {
        "source_account": account,
        "isin": single(get("isin")),
        "trade_time": timestamp(get("time")),
        "quantity": decimal(get("qty")),
        "price": decimal(get("price")),
        "trade_amount": decimal(get("amount")),
        "currency": single(get("currency")),
    }
    return {
        "section": "pending" if pending else "completed",
        "ordinal": ordinal,
        "state": "pending" if pending else "settled",
        "ids": ids,
        "identity": digest([PROVIDER, account, ids]) if len(ids) == 2 else None,
        "core": core,
        "settlement_date": day(get("settlement"), optional=True),
        "depo_settlement_date": day(get("depo"), optional=True),
        "settlement_time": timestamp(get("settlement_time"), optional=True),
        "bank_commission": decimal(get("commission"), optional=True),
        "accrued_interest": decimal(get("nkd"), optional=True),
        "repo_observed": bool(lines(get("repo"))),
        **_face_value_fields(row, pending=pending),
    }


def parse_mybroker(
    document: bytes, filename: str, *, money_linkage_version: str | None = MONEY_LINKAGE
) -> dict:
    if money_linkage_version not in (None, MONEY_LINKAGE):
        raise MyBrokerError("money_linkage_version_unsupported")
    match = FILENAME.fullmatch(filename)
    if not match:
        raise MyBrokerError("filename_range_invalid")
    try:
        # This grammar uses a two-digit year; Python's strict %y interpretation is fixed.
        start, end = [datetime.strptime(match[key], "%d.%m.%y").date() for key in ("start", "end")]
    except ValueError:
        raise MyBrokerError("filename_range_invalid") from None
    if start > end:
        raise MyBrokerError("filename_range_invalid")
    if not document or len(document) > MAX_BYTES:
        raise MyBrokerError("document_size_invalid")
    try:
        xml = document.decode("utf-8-sig")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise MyBrokerError("xml_declarations_unsupported")
        root = ET.fromstring(xml)
    except (UnicodeError, ET.ParseError):
        raise MyBrokerError("xml_invalid") from None
    stack = [(root, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > 100000 or depth > 32:
            raise MyBrokerError("xml_bounds_exceeded")
        stack.extend((child, depth + 1) for child in node)
    if (
        root.tag != "{MyBroker}Report"
        or root.get("Name") != "MyBroker"
        or root.get("Textbox5") != "Отчет по сделкам и операциям (Отчет брокера)"
        or root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation") != SCHEMA
    ):
        raise MyBrokerError("family_unsupported")
    sections = {}
    for outer, name in SECTIONS.items():
        wrappers = root.findall(f"m:{outer}", NS)
        reports = wrappers[0].findall("m:Report", NS) if len(wrappers) == 1 else []
        if len(reports) != 1 or reports[0].get("Name") != name:
            raise MyBrokerError("required_section_invalid")
        sections[outer] = reports[0]
    blockers = []
    # Validate the whole wrapper, not just the selected Report subtree.
    if any(list(root.find(f"m:{outer}", NS)) != [report] for outer, report in sections.items()):
        blockers.append("unparsed_source_rows")
    allowed_tags = {
        "Positions": {
            "Report",
            "Tablix1",
            "active_type_Collection",
            "active_type",
            "Details_Collection",
            "Details",
        },
        "Trades": {
            "Report",
            "Tablix2",
            "Tablix3",
            "Details_Collection",
            "Details",
            "Details2_Collection",
            "Details2",
        },
        "Trades2": {
            "Report",
            "Tablix1",
            "settlement_date_Collection",
            "settlement_date",
            "rn_Collection",
            "rn",
            "oper_type",
            "comment",
            "Textbox11",
            "money_volume_begin1_Collection",
            "money_volume_begin1",
            "p_code_Collection",
            "p_code",
        },
    }
    for outer, tags in allowed_tags.items():
        if any(
            node.tag not in {f"{{MyBroker}}{tag}" for tag in tags}
            for node in sections[outer].iter()
        ):
            blockers.append("unparsed_source_rows")
    if any(child.tag not in {f"{{MyBroker}}{name}" for name in SECTIONS} for child in root):
        blockers.append("unknown_section")
    positions = []
    position_keys = set()
    rub_money = []
    endpoint_blockers = set()
    endpoint_conflicts = set()
    consumed_positions = 0
    position_groups = sections["Positions"].findall(
        "m:Tablix1/m:active_type_Collection/m:active_type", NS
    )
    for i, row in enumerate(
        row
        for group in position_groups
        for row in group.findall("m:Details_Collection/m:Details", NS)
    ):
        consumed_positions = i + 1
        isin = single(row.get("ISIN1"), optional=True)
        if isin is not None:
            position = {
                "section": "positions",
                "ordinal": i,
                "source_account": single(row.get("acc_code")),
                "isin": isin,
                "actual_quantity": decimal(row.get("real_rest")),
                "forward_quantity": decimal(row.get("forward_rest")),
                "beginning_actual_quantity": decimal(row.get("income_rest"), optional=True),
                "beginning_value": decimal(row.get("income_volume"), optional=True),
                "ending_value": decimal(row.get("real_volume"), optional=True),
                **_face_value_fields(row),
            }
            key = (position["source_account"], isin)
            if key in position_keys:
                endpoint_conflicts.add("duplicate_position")
            position_keys.add(key)
            positions.append(position)
            if position["beginning_actual_quantity"] is None:
                endpoint_blockers.add("endpoint_beginning_quantity_unavailable")
            if position["beginning_value"] is None or position["ending_value"] is None:
                endpoint_blockers.add("endpoint_value_unavailable")
            continue
        # The accepted conjunction is row-level: active_type=Валюта +
        # active_name=RUB + empty ISIN1. There is no inherited group placement;
        # anything else stays a visible, fail-closed blocker.
        if (
            single(row.get("active_type"), optional=True) == CURRENCY_TYPE
            and single(row.get("active_name"), optional=True) == CURRENCY_NAME
        ):
            rub_money.append(
                {
                    "section": "rub_money",
                    "ordinal": i,
                    "source_account": single(row.get("acc_code")),
                    "currency": "RUB",
                    "beginning_amount": decimal(row.get("income_rest"), optional=True),
                    "ending_amount": decimal(row.get("real_rest"), optional=True),
                }
            )
            continue
        endpoint_blockers.add("position_row_unclassified")
    if positions and not rub_money:
        # Absence is not observed zero RUB money.
        endpoint_blockers.add("rub_money_unavailable")
    if rub_money and any(
        row["beginning_amount"] is None or row["ending_amount"] is None for row in rub_money
    ):
        endpoint_blockers.add("rub_money_incomplete")
    if len(rub_money) > 1:
        # Multiple matching currency rows give no unambiguous RUB money evidence.
        endpoint_conflicts.add("rub_money_ambiguous")
    trades = []
    for pending, path in (
        (False, "m:Tablix2/m:Details_Collection/m:Details"),
        (True, "m:Tablix3/m:Details2_Collection/m:Details2"),
    ):
        for i, row in enumerate(sections["Trades"].findall(path, NS)):
            trades.append(_trade(row, pending=pending, ordinal=i))
    money = []
    consumed_amounts = set()
    native_linkage_observed = False
    groups = sections["Trades2"].findall(
        "m:Tablix1/m:settlement_date_Collection/m:settlement_date", NS
    )
    for group in groups:
        settled = timestamp(group.get("settlement_date"), iso=True)
        if not settled.endswith("T00:00:00"):
            raise MyBrokerError("money_date_invalid")
        for rn in group.findall("m:rn_Collection/m:rn", NS):
            operations = rn.findall("m:oper_type", NS)
            if len(operations) != 1:
                raise MyBrokerError("money_row_invalid")
            op = operations[0]
            comments = op.findall("m:comment", NS)
            if len(comments) != 1:
                raise MyBrokerError("money_row_invalid")
            comment = comments[0]
            accounts = comment.findall("m:Textbox11", NS)
            if len(accounts) != 1:
                raise MyBrokerError("money_row_invalid")
            # Only the exact approved linkage strings carry semantics. Other text is discarded.
            legacy_linkage = LINKAGE.fullmatch(comment.get("comment", ""))
            native_linkage = LINKAGE.fullmatch(op.get("oper_type", ""))
            if (
                native_linkage
                and legacy_linkage
                and native_linkage.groups() != legacy_linkage.groups()
            ):
                raise MyBrokerError("money_linkage_conflict")
            native_linkage_observed |= native_linkage is not None
            linkage = (
                native_linkage or legacy_linkage
                if money_linkage_version == MONEY_LINKAGE
                else legacy_linkage
            )
            amounts = comment.findall(
                "m:money_volume_begin1_Collection/m:money_volume_begin1/"
                "m:p_code_Collection/m:p_code/m:p_code",
                NS,
            )
            if not amounts:
                raise MyBrokerError("money_row_invalid")
            for amount in amounts:
                consumed_amounts.add(amount)
                money.append(
                    {
                        "section": "money",
                        "ordinal": len(money),
                        "source_account": single(accounts[0].get("acc_code")),
                        "date": settled[:10],
                        "last_update": timestamp(rn.get("last_update"), iso=True),
                        "kind": ("settlement" if linkage[1] == "Расчеты" else "commission")
                        if linkage
                        else "unsupported",
                        "primary_id": linkage[2] if linkage else None,
                        "amount": decimal(amount.get("volume")),
                        "currency": single(amount.get("p_code")),
                    }
                )
    if any(
        node.tag == "{MyBroker}p_code" and "volume" in node.attrib and node not in consumed_amounts
        for node in root.iter()
    ):
        blockers.append("unparsed_source_rows")
    for outer in ("Trades3", "Trades4"):
        # Opaque section semantics: retain no raw rows, only a visible blocker/count.
        if len(sections[outer]):
            blockers.append(f"{SECTIONS[outer]}_unsupported")
    # Any Details/rn outside the frozen paths is material, never silently complete.
    # Every Positions Details row is consumed above (security, RUB currency or a
    # visible unclassified blocker), so only truly unvisited nodes remain unparsed.
    for outer, parsed_count, tag in (
        ("Positions", consumed_positions, "Details"),
        ("Trades", len(trades), None),
        ("Trades2", sum(len(g.findall("m:rn_Collection/m:rn", NS)) for g in groups), "rn"),
    ):
        observed = sum(
            1
            for node in root.find(f"m:{outer}", NS).iter()
            if node.tag
            in (
                {"{MyBroker}Details", "{MyBroker}Details2"}
                if tag is None
                else {f"{{MyBroker}}{tag}"}
            )
        )
        if observed != parsed_count:
            blockers.append("unparsed_source_rows")
    if consumed_positions + len(trades) + len(money) > MAX_ROWS:
        raise MyBrokerError("row_limit_exceeded")
    return {
        "provider": PROVIDER,
        "parser": PARSER,
        **(
            {"money_linkage_version": MONEY_LINKAGE}
            if native_linkage_observed and money_linkage_version == MONEY_LINKAGE
            else {}
        ),
        "document_sha256": hashlib.sha256(document).hexdigest(),
        "filename_account": match["account"],
        "covered_from": start.isoformat(),
        "covered_to": end.isoformat(),
        "positions": positions,
        "rub_money": rub_money,
        "endpoint_basis": {
            "beginning_value": "previous_day_eod",
            "ending_value": "covered_to_eod",
        },
        "endpoint_blockers": sorted(endpoint_blockers),
        "endpoint_conflicts": sorted(endpoint_conflicts),
        "trades": trades,
        "money": money,
        "section_inventory": {
            name: sum(1 for _ in root.find(f"m:{outer}", NS).iter()) - 2
            for outer, name in SECTIONS.items()
            for report in [sections[outer]]
        },
        "syntax_blockers": sorted(set(blockers)),
    }
