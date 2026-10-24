"""Structural exclusions for provisional source-return reads only.

Use the verified whole-tree inventory, never rewrite frozen S1 or grant receipt
authority. Display scalars stay opaque: their hashes cannot prove numeric/date
validity and are never used as money, events, endpoints or report periods.
Known labels, namespaces, keys, paths and cardinalities remain exact. This is
deliberately separate from the stronger original-byte incomplete-DRAFT proof.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time
from decimal import Decimal
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import SCHEMA, SECTIONS, digest
from hermes_finance.statement_import.mybroker_draft_structure import (
    _ATTRS,
    _PATHS,
    BLANKS,
    DAILY,
    DEBT,
    FOOTER,
    SUMMARIES,
    TOTAL,
    N,
    _endpoint,
    _shape,
    _summary,
    _visited,
)
from hermes_finance.statement_import.mybroker_metadata import _section_shape

_WHITESPACE = {digest(None), digest("")}
for _newline in ("", "\n", "\r\n"):
    for _indent in (" ", "\t"):
        _WHITESPACE.update(digest(_newline + _indent * count) for count in range(129))

_LABELS = {
    "Textbox217": ("Предварительный расчет обязательств по НДФЛ",),
    "oper_group": (
        "Внесено по распоряжению Клиента",
        "Дивиденды",
        "Купоны",
        "Списано по распоряжению Клиента",
        "Списано по тарифам Банка",
    ),
    "p_code1": ("RUB",),
    "p_code2": ("RUB",),
    "p_code6": ("RUB",),
    "p_code": ("RUB",),
}

_RETURN_SUMMARIES = SUMMARIES + (
    _summary(
        (
            "Внесено по распоряжению Клиента",
            "Дивиденды",
            "Купоны",
            "Списано по распоряжению Клиента",
            "Списано по тарифам Банка",
        )
    ),
)


def _inventory_tree(observations, *, references=None):
    nodes = {}
    counts = {}
    for row in observations:
        if row["section"] != "structure":
            continue
        facts, locator = row["facts"], row["locator"]
        if (
            row["row_class"] != "opaque_inventory"
            or locator in nodes
            or facts["text_digest"] not in _WHITESPACE
            or facts["tail_digest"] not in _WHITESPACE
        ):
            raise ValueError
        attrs = {a["name"]: a["value_digest"] for a in facts["attributes"]}
        if len(attrs) != len(facts["attributes"]):
            raise ValueError
        node = ET.Element(facts["tag"], attrs)
        if references is not None:
            references[id(node)] = facts.get("native_references", {})
        nodes[locator], counts[locator] = node, facts["child_count"]
        if locator != "0":
            parent, index = locator.rsplit("/", 1)
            if str(len(nodes[parent])) != index:
                raise ValueError
            nodes[parent].append(node)
    if not nodes or any(len(node) != counts[path] for path, node in nodes.items()):
        raise ValueError
    return nodes["0"]


def _opaque_shape(spec):
    """Reuse the DRAFT tree grammar, checking label hashes, ignoring scalar values."""
    tag, attrs, children = spec
    checks = {}
    for key, check in attrs.items():
        if key in _LABELS:
            allowed = {digest(value) for value in _LABELS[key] if check(value)}
            checks[key] = lambda value, allowed=allowed: value in allowed
        else:
            # Presence/empty is observable; arbitrary scalar content is not.
            checks[key] = lambda value, empty=check(""): empty or value != digest("")
    return tag, checks, tuple(_opaque_shape(child) for child in children)


def _service(wrapper, outer):
    """Same metadata topology/constants; connection dates are opaque, never periods."""
    return _section_shape(
        wrapper,
        outer,
        scalar=digest,
        valid_start=lambda value: value not in {digest(""), digest("-")},
    )


def _repo_zero_field(node, trade, references):
    """Recognize one opaque REPO field without granting any REPO economics."""
    native = references.get(id(node), {})
    own, partner = native.get("trade_no", ""), native.get("repo_no", "")
    return (
        node.get("course3") == digest("0.0000")
        and re.fullmatch(r"B[0-9]{1,127}", own) is not None
        and re.fullmatch(r"B[0-9]{1,127}", partner) is not None
        and own != partner
        and node.get("trade_no") == digest(own)
        and node.get("repo_no") == digest(partner)
        and node.get("comment") in {digest("репо ч.1"), digest("репо ч.2")}
        and trade.get("ids") == [own]
        and trade.get("identity") is None
        and trade.get("repo_observed") is True
        and node.get("acc_code") == digest(trade["core"]["source_account"])
        and node.get("isin_reg") == digest(trade["core"]["isin"])
    )


def _recognized(root, source, references, *, cancellation_tree=None):
    expected = {
        "Name": digest("MyBroker"),
        "Textbox5": digest("Отчет по сделкам и операциям (Отчет брокера)"),
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": digest(SCHEMA),
    }
    if "Textbox6" in root.attrib:
        expected["Textbox6"] = digest("Уполномоченное лицо")
    if (
        root.tag != N + "Report"
        or root.attrib != expected
        or [n.tag for n in root] != [N + name for name in SECTIONS]
    ):
        return False
    for wrapper, (outer, name) in zip(root, SECTIONS.items(), strict=True):
        if (
            wrapper.attrib
            or len(wrapper) != 1
            or wrapper[0].tag != N + "Report"
            or wrapper[0].attrib != {"Name": digest(name)}
            or sum(1 for _ in wrapper[0].iter()) - 1 != source["section_inventory"][name]
        ):
            return False
        report = wrapper[0]
        if outer in {"Trades3", "Trades4"}:
            cancellation = (
                outer == "Trades3"
                and cancellation_tree is not None
                and ET.tostring(wrapper) == cancellation_tree
            )
            if len(report) and not _service(wrapper, outer) and not cancellation:
                return False
            continue
        order = {
            "Positions": ("Tablix1", "Tablix3"),
            "Trades": ("Tablix2", "Tablix3"),
            "Trades2": (
                "Tablix2",
                "Tablix1",
                "Tablix3",
                "Tablix5",
                "Tablix4",
                "Tablix6",
                "Tablix7",
            ),
        }[outer]
        actual = [node.tag.removeprefix(N) for node in report]
        if actual != [tag for tag in order if tag in actual]:
            return False
        shapes = {"Tablix3": (FOOTER,)} if outer == "Positions" else {}
        if outer == "Trades2":
            shapes = {
                "Tablix2": (_endpoint(True),),
                "Tablix3": (_endpoint(False),),
                **{key: (value,) for key, value in BLANKS.items()},
                "Tablix7": _RETURN_SUMMARIES,
            }
        for tag, variants in shapes.items():
            found = report.findall(N + tag)
            if found:
                if len(found) != 1 or not any(_shape(found[0], _opaque_shape(s)) for s in variants):
                    return False
                report.remove(found[0])
        if outer == "Trades2":
            for group in report.findall(".//" + N + "settlement_date"):
                rows = group.findall(N + "rn_Collection/" + N + "rn")
                for index, row in enumerate(rows):
                    comment = row.find(N + "oper_type/" + N + "comment")
                    if comment is None:
                        return False
                    if any(child.tag in {N + "Textbox95", N + "Textbox93"} for child in comment):
                        if [child.tag for child in comment] != [
                            N + tag
                            for tag in (
                                "money_volume_begin1_Collection",
                                "Textbox95",
                                "Textbox93",
                                "Textbox11",
                            )
                        ]:
                            return False
                        values = [
                            comment[1][0].get("money_volume"),
                            comment[1][1].get("all_volume"),
                            comment[2].get("debet_volume"),
                        ]
                        if any(
                            (value == digest("")) != (index < len(rows) - 1) for value in values
                        ):
                            return False
            for parent in report.iter():
                for child in list(parent):
                    tag = child.tag.removeprefix(N)
                    spec = (
                        TOTAL
                        if tag == "Textbox116" and parent.tag == N + "Tablix1"
                        else DAILY
                        if tag == "Textbox95" and parent.tag == N + "comment"
                        else DEBT
                        if tag == "Textbox93" and parent.tag == N + "comment"
                        else None
                    )
                    if spec:
                        if not _shape(child, _opaque_shape(spec)):
                            return False
                        parent.remove(child)
        allowed = {"Report"}
        for path in _PATHS[outer]:
            parts = ("Report/" + path).split("/")
            allowed.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        attrs = {path: set(keys) for path, keys in _ATTRS[outer].items()}
        if outer == "Trades":
            rows = report.findall(N + "Tablix2/" + N + "Details_Collection/" + N + "Details")
            trades = [t for t in source["trades"] if t["section"] == "completed"]
            if len(rows) != len(trades):
                return False
            for row, trade in zip(rows, trades, strict=True):
                if "course3" in row.attrib and not _repo_zero_field(row, trade, references):
                    return False
            attrs["Report/Tablix2/Details_Collection/Details"].add("course3")
        for path, keys in attrs.items():
            if path.endswith(("/Details", "/Details2")):
                keys.update({"face_value", "nominal", "nominal_value"})
                if path.endswith("/Details2"):
                    keys.update(
                        {
                            "face_value2",
                            "nominal2",
                            "nominal_value2",
                            "p_name2",
                            "Textbox16",
                            "place_name2",
                        }
                    )
        if not _visited(report, "Report", allowed, attrs):
            return False
    for outer, tag, expected_count in (
        ("Positions", "Details", len(source["positions"]) + len(source["rub_money"])),
        ("Trades", "Details", sum(t["section"] == "completed" for t in source["trades"])),
        ("Trades", "Details2", sum(t["section"] == "pending" for t in source["trades"])),
        ("Trades2", "p_code", len(source["money"])),
    ):
        count = sum(
            n.tag == N + tag and (tag != "p_code" or "volume" in n.attrib)
            for n in root.find(N + outer).iter()
        )
        if count != expected_count:
            return False
    return True


def original_cancellation_dates(view, original):
    """Bound explicit custody cancellations to their source-booked dates only.

    Exact original bytes, not scalar hashes, prove these dates. This recognizes
    neither principal cash nor an effective economic date: every cancellation
    month remains financially uncertain. Any other Transfers grammar stays
    document-wide. The caller additionally verifies filename/parser/currentness.
    """
    if hashlib.sha256(original).hexdigest() != view["document_sha256"]:
        return None
    try:
        raw = ET.fromstring(
            original.decode("utf-8-sig"),
            parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)),
        )
        refs = {}
        inventory = _inventory_tree(view["observations"], references=refs)
        raw_nodes, saved_nodes = list(raw.iter()), list(inventory.iter())
        if len(raw_nodes) != len(saved_nodes) or any(
            a.tag != b.tag
            or {key: digest(value) for key, value in a.attrib.items()} != b.attrib
            or len(a) != len(b)
            or (a.text or "").strip()
            or (a.tail or "").strip()
            for a, b in zip(raw_nodes, saved_nodes, strict=True)
        ):
            return None
        wrapper = raw.find(N + "Trades3")
        if wrapper is None or wrapper.attrib or len(wrapper) != 1:
            return None
        report = wrapper[0]
        if report.tag != N + "Report" or report.attrib != {"Name": "4_Transfers"}:
            return None
        if len(report) != 1 or report[0].tag != N + "Tablix1" or report[0].attrib:
            return None
        table = report[0]
        if len(table) != 1 or table[0].tag != N + "Details_Collection" or table[0].attrib:
            return None
        rows = table[0]
        if not len(rows):
            return None
        accounts = {
            row.get("source_account")
            for key in ("positions", "rub_money", "money")
            for row in view["document"][key]
        }
        accounts.update(t["core"]["source_account"] for t in view["document"]["trades"])
        if len(accounts) != 1 or None in accounts:
            return None
        expected = {
            "settlement_date",
            "settlement_time",
            "place_name",
            "oper_type",
            "p_name",
            "comment_new",
            "qty",
            "acc_code",
        }
        dates = []
        for row in rows:
            if row.tag != N + "Details" or len(row) or set(row.attrib) != expected:
                return None
            attrs = row.attrib
            if (
                attrs["acc_code"] not in accounts
                or attrs["place_name"] != "НРД"
                or attrs["oper_type"] != "Перевод"
                or not re.fullmatch(r"Аннулирование выпуска [A-Z0-9]{1,32}\.", attrs["comment_new"])
                or not re.fullmatch(r"[^\r\n]{1,256}\r\n[A-Z]{2}[A-Z0-9]{9}[0-9]", attrs["p_name"])
                or not re.fullmatch(r"-[0-9]{1,18}(?:\.[0-9]{1,10})?", attrs["qty"])
                or Decimal(attrs["qty"]) >= 0
                or not re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00", attrs["settlement_date"]
                )
                or not re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}", attrs["settlement_time"])
            ):
                return None
            booked = datetime.fromisoformat(attrs["settlement_date"]).date()
            time.fromisoformat(attrs["settlement_time"])
            if (
                not date.fromisoformat(view["covered_from"])
                <= booked
                <= date.fromisoformat(view["covered_to"])
            ):
                return None
            dates.append(booked)
        saved_wrapper = inventory.find(N + "Trades3")
        if not _recognized(
            inventory,
            view["document"],
            refs,
            cancellation_tree=ET.tostring(saved_wrapper),
        ):
            return None
        return tuple(dates)
    except (ValueError, TypeError, KeyError, IndexError, ET.ParseError):
        return None


def source_return_blockers(view):
    """Recompute ONLY the provisional read's exclusions from verified inventory.

    Missing/unrecognized evidence leaves all frozen warnings intact. No change
    to intake DTOs, normalized facts, Save/replay, strict DRAFT or financial Apply.
    """
    source = view["document"]
    blockers = set(source.get("syntax_blockers", []))
    candidates = {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"}
    if not blockers.intersection(candidates):
        return blockers
    try:
        references = {}
        root = _inventory_tree(view.get("observations", []), references=references)
        if _recognized(root, source, references):
            return blockers - candidates
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    return blockers
