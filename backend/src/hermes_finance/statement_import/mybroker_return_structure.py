"""Structural exclusions for provisional source-return reads only.

Use the verified whole-tree inventory, never rewrite frozen S1 or grant receipt
authority. Display scalars stay opaque: their hashes cannot prove numeric/date
validity and are never used as money, events, endpoints or report periods.
Known labels, namespaces, keys, paths and cardinalities remain exact. This is
deliberately separate from the stronger original-byte incomplete-DRAFT proof.
"""

from __future__ import annotations

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
        "Списано по тарифам Банка",
    ),
    "p_code1": ("RUB",),
    "p_code2": ("RUB",),
    "p_code6": ("RUB",),
    "p_code": ("RUB",),
}


def _inventory_tree(observations):
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


def _recognized(root, source):
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
            if len(report) and not _service(wrapper, outer):
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
                "Tablix7": SUMMARIES,
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
        if _recognized(_inventory_tree(view.get("observations", [])), source):
            return blockers - candidates
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    return blockers
