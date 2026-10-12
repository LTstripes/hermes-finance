"""Bounded identity eligibility for incomplete DRAFT, never source completeness.

Only named Positions/Money side branches may be deferred. Their values are
uninterpreted source evidence, not tax, cash, valuation or event authority.
S1 bytes, normalized shape and blockers are never edited by this projection.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import NS, SECTIONS, MyBrokerError
from hermes_finance.statement_import.mybroker_empty_money import _OriginalTree, _white

CONTRACT = "mybroker-incomplete-draft-identity-v1"
N = "{MyBroker}"


def _number(value, *, places=10, empty=False):
    return (empty and value == "") or (
        len(value) <= 48 and re.fullmatch(rf"-?[0-9]+\.[0-9]{{{places}}}", value) is not None
    )


def _currency(value):
    return re.fullmatch(r"[A-Z]{3}", value) is not None


def _label(value):
    return 0 < len(value) <= 128 and not any(c in value for c in "\r\n\t")


def _shape(node, spec):
    """Exact ordered tree, exact attribute keys, bounded scalar leaves."""
    tag, attrs, children = spec
    if (
        node.tag != N + tag
        or set(node.attrib) != set(attrs)
        or not all(check(node.attrib[key]) for key, check in attrs.items())
        or not _white(node.text)
        or not _white(node.tail)
    ):
        return False
    if isinstance(children, list):  # One or more homogeneous summary groups.
        keys = [tuple(sorted(child.attrib.items())) for child in node]
        return (
            bool(len(node))
            and len(keys) == len(set(keys))
            and all(_shape(child, children[0]) for child in node)
        )
    return len(node) == len(children) and all(
        _shape(child, expected) for child, expected in zip(node, children, strict=True)
    )


def _branch(tag, *children, **attrs):
    return tag, attrs, tuple(children)


def _chain(tags, leaf):
    for tag in reversed(tags.split("/")):
        leaf = _branch(tag, leaf)
    return leaf


FOOTER = _branch(
    "Tablix3",
    _branch(
        "Details1_Collection",
        _branch(
            "Details1",
            Textbox222=lambda v: _number(v, places=2) and not v.startswith("-"),
            fSUMPAYED=lambda v: _number(v, places=2) and not v.startswith("-"),
            fTOPAY=lambda v: _number(v, places=2) and not v.startswith("-"),
        ),
    ),
    Textbox217=lambda v: v == "Предварительный расчет обязательств по НДФЛ",
)


def _endpoint(beginning):
    number = "1" if beginning else "2"
    word = "begin" if beginning else "end"
    return _branch(
        "Tablix2" if beginning else "Tablix3",
        _branch(
            "Textbox1" if beginning else "Textbox2",
            _chain(
                f"money_volume_{word}_Collection/money_volume_{word}/"
                f"p_code{number}_Collection/p_code{number}",
                _branch(
                    f"p_code{number}",
                    **{f"p_code{number}": _currency, f"volume{number}": _number},
                ),
            ),
            _branch(
                "Textbox58" if beginning else "Textbox59",
                _branch(
                    "Textbox39" if beginning else "Textbox42",
                    **{"money_volume_begin" + ("" if beginning else "2"): _number},
                ),
                _branch(
                    "Textbox43" if beginning else "Textbox44",
                    **{"all_volume_begin" + ("" if beginning else "2"): _number},
                ),
            ),
        ),
    )


BLANKS = {
    "Tablix5": _chain(
        "Tablix5/Textbox3", _branch("Textbox61", _branch("Textbox46"), _branch("Textbox47"))
    ),
    "Tablix4": _chain(
        "Tablix4/Textbox125/Textbox118/Textbox119",
        _branch(
            "Textbox117",
            _branch("Textbox96", _branch("Textbox85"), _branch("Textbox87")),
            _branch("Textbox94"),
            _branch("Textbox26"),
        ),
    ),
    "Tablix6": _chain(
        "Tablix6/Textbox4", _branch("Textbox63", _branch("Textbox49"), _branch("Textbox50"))
    ),
}
SUMMARY = _branch(
    "Tablix7",
    (
        "oper_group_Collection",
        {},
        [
            _branch(
                "oper_group",
                _branch(
                    "p_code6_Collection", _branch("p_code6", p_code6=_currency, volume6=_number)
                ),
                oper_group=_label,
            ),
        ],
    ),
)
DAILY = _branch(
    "Textbox95",
    _branch("Textbox83", money_volume=lambda v: _number(v, empty=True)),
    _branch("Textbox84", all_volume=lambda v: _number(v, empty=True)),
)
DEBT = _branch("Textbox93", debet_volume=lambda v: _number(v, empty=True))
TOTAL = _chain(
    "Textbox116/Textbox105/Textbox110",
    _branch(
        "Textbox111",
        _chain(
            "money_volume_begin1_Collection/money_volume_begin1/p_code_Collection/p_code",
            _branch("p_code", p_code=_currency, Textbox112=_number),
        ),
        _branch("Textbox95", _branch("Textbox83"), _branch("Textbox84")),
        _branch("Textbox93"),
        _branch("Textbox11"),
    ),
)

# After removing ONLY validated side branches, every remaining node must be on
# a consumed S1 row path. Tag allowlisting alone would miss moved Details/rn.
_PATHS = {
    "Positions": ["Tablix1/active_type_Collection/active_type/Details_Collection/Details"],
    "Trades": ["Tablix2/Details_Collection/Details", "Tablix3/Details2_Collection/Details2"],
    "Trades2": [
        "Tablix1/settlement_date_Collection/settlement_date/rn_Collection/rn/oper_type/comment/Textbox11",
        "Tablix1/settlement_date_Collection/settlement_date/rn_Collection/rn/oper_type/comment/"
        "money_volume_begin1_Collection/money_volume_begin1/p_code_Collection/p_code/p_code",
    ],
}


def _visited(node, prefix, allowed):
    return (
        prefix in allowed
        and all(
            _visited(child, prefix + "/" + child.tag.removeprefix(N), allowed) for child in node
        )
        and node.tag.startswith(N)
        and _white(node.text)
        and _white(node.tail)
    )


def draft_structure_exceptions(document: bytes) -> list[str] | None:
    """Return classifications only if ALL unparsed content is bounded here.

    Called only after authoritative S1 parsing. None is a hard identity blocker.
    No source hash is supplied by the caller: parse_identity binds original bytes.
    """
    try:
        root = ET.fromstring(
            document.decode("utf-8-sig"), parser=ET.XMLParser(target=_OriginalTree())
        )
    except MyBrokerError:
        return None
    exceptions = []
    for outer in _PATHS:
        wrapper = root.find("m:" + outer, NS)
        if (
            wrapper.attrib
            or len(wrapper) != 1
            or not _white(wrapper.text)
            or not _white(wrapper.tail)
        ):
            return None
        report = wrapper[0]
        if report.attrib != {"Name": SECTIONS[outer]}:
            return None
        if outer == "Positions":
            footers = report.findall("m:Tablix3", NS)
            if footers:
                if len(footers) != 1 or not _shape(footers[0], FOOTER):
                    return None
                report.remove(footers[0])
                exceptions.append("positions_tax_footer_unresolved")
        if outer == "Trades2":
            shapes = {
                "Tablix2": _endpoint(True),
                "Tablix3": _endpoint(False),
                **BLANKS,
                "Tablix7": SUMMARY,
            }
            for tag, spec in shapes.items():
                found = report.findall("m:" + tag, NS)
                if found:
                    if len(found) != 1 or not _shape(found[0], spec):
                        return None
                    report.remove(found[0])
                    exceptions.append("money_controls_unresolved")
            tables = report.findall("m:Tablix1", NS)
            if len(tables) != 1:
                return None
            table = tables[0]
            totals = table.findall("m:Textbox116", NS)
            if totals:
                if len(totals) != 1 or not _shape(totals[0], TOTAL):
                    return None
                table.remove(totals[0])
                exceptions.append("money_controls_unresolved")
            comments = table.findall(
                "m:settlement_date_Collection/m:settlement_date/m:rn_Collection/m:rn/m:oper_type/m:comment",
                NS,
            )
            for comment in comments:
                for tag, spec in (("Textbox95", DAILY), ("Textbox93", DEBT)):
                    found = comment.findall("m:" + tag, NS)
                    if found:
                        if len(found) != 1 or not _shape(found[0], spec):
                            return None
                        comment.remove(found[0])
                        exceptions.append("money_controls_unresolved")
        allowed = {"Report"}
        for path in _PATHS[outer]:
            parts = ("Report/" + path).split("/")
            allowed.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        if not _visited(report, "Report", allowed):
            return None
    return sorted(set(exceptions)) if exceptions else None
