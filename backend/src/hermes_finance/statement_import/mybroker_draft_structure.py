"""Bounded identity eligibility for incomplete DRAFT, never source completeness.

Only named Positions/Money side branches may be deferred. Their values are
uninterpreted source evidence, not tax, cash, valuation or event authority.
S1 bytes, normalized shape and blockers are never edited by this projection.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import NS, SCHEMA, SECTIONS, MyBrokerError
from hermes_finance.statement_import.mybroker_empty_money import _OriginalTree, _white
from hermes_finance.statement_import.mybroker_metadata import _safe

CONTRACT = "mybroker-incomplete-draft-identity-v1"
N = "{MyBroker}"


def _number(value, *, places=None, empty=False):
    if empty and value == "":
        return True
    pattern = rf"-?[0-9]+\.[0-9]{{{places}}}" if places else r"-?[0-9]+(?:\.[0-9]+)?"
    if len(value) > 48 or re.fullmatch(pattern, value) is None:
        return False
    with localcontext() as context:
        context.prec = 100
        minor = Decimal(value) * 100
        return minor == minor.to_integral_value()


def _currency(value):
    return value == "RUB"


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


def _summary(labels):
    return _branch(
        "Tablix7",
        _branch(
            "oper_group_Collection",
            *(
                _branch(
                    "oper_group",
                    _branch(
                        "p_code6_Collection", _branch("p_code6", p_code6=_currency, volume6=_number)
                    ),
                    oper_group=lambda v, expected=label: v == expected,
                )
                for label in labels
            ),
        ),
    )


# Three complete observed trees, not a grammar of optional economic groups.
# Totals remain opaque bookkeeping exceptions with no financial authority.
SUMMARIES = tuple(
    _summary(labels)
    for labels in (
        ("Внесено по распоряжению Клиента", "Купоны", "Списано по тарифам Банка"),
        ("Внесено по распоряжению Клиента", "Дивиденды", "Купоны", "Списано по тарифам Банка"),
        ("Дивиденды", "Купоны", "Списано по тарифам Банка"),
    )
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


# Consumed row keys and separately observed caption keys are path-specific.
# A valid side branch must never make an unseen identity attribute elsewhere
# eligible. Group wrappers have no attrs; no wildcard Textbox/native-ID keys.
_ATTRS = {
    "Positions": {
        "Report": {"Name"},
        "Report/Tablix1": set(
            "Textbox14 Textbox187 Textbox196 Textbox23 Textbox28 Textbox30 Textbox37 Textbox48 Textbox54 Textbox56 Textbox65 Textbox84 Textbox86".split()
        ),
        "Report/Tablix1/active_type_Collection/active_type/Details_Collection/Details": set(
            "ISIN1 acc_code active_name active_type forward_rest income_rest income_volume place real_rest real_volume".split()
        ),
    },
    "Trades": {
        "Report": {"Name"},
        "Report/Tablix2": set(
            "Textbox118 Textbox134 Textbox135 Textbox149 Textbox180 Textbox25 Textbox31 Textbox4 Textbox40 Textbox52 Textbox64 Textbox73 Textbox86".split()
        ),
        "Report/Tablix3": set(
            "Textbox112 Textbox121 Textbox127 Textbox13 Textbox137 Textbox138 Textbox156 Textbox161 Textbox167 Textbox168 Textbox173 Textbox178 Textbox35".split()
        ),
        "Report/Tablix2/Details_Collection/Details": set(
            "trade_no acc_code isin_reg db_time qty Price summ_trade summ_nkd curr_calc bank_tax save_settlement_date save_depo_settlement_date settlement_time repo_no comment p_name Textbox14 place_name".split()
        ),
        "Report/Tablix3/Details2_Collection/Details2": set(
            "trade_no1 acc_code2 isin_reg1 db_time2 qty2 Price2 summ_trade2 summ_nkd2 curr_calc2 bank_tax2 save_settlement_date3 save_depo_settlement_date3 settlement_time2 repo_no1".split()
        ),
    },
    "Trades2": {"Report": {"Name"}},
}
_MONEY_ROW = "Report/Tablix1/settlement_date_Collection/settlement_date"
for _path, _keys in (
    (_MONEY_ROW, {"settlement_date"}),
    (_MONEY_ROW + "/rn_Collection/rn", {"last_update"}),
    (_MONEY_ROW + "/rn_Collection/rn/oper_type", {"oper_type"}),
    (_MONEY_ROW + "/rn_Collection/rn/oper_type/comment", {"comment"}),
    (_MONEY_ROW + "/rn_Collection/rn/oper_type/comment/Textbox11", {"acc_code"}),
    (
        _MONEY_ROW
        + "/rn_Collection/rn/oper_type/comment/money_volume_begin1_Collection/money_volume_begin1/p_code_Collection/p_code/p_code",
        {"p_code", "volume"},
    ),
):
    _ATTRS["Trades2"][_path] = _keys


_REPEATED = {
    "active_type_Collection",
    "Details_Collection",
    "Details2_Collection",
    "rn_Collection",
    "settlement_date_Collection",
}


def _visited(node, prefix, allowed, attrs, *, exact_attrs=False):
    expected = [p.rsplit("/", 1)[1] for p in allowed if "/" in p and p.rsplit("/", 1)[0] == prefix]
    actual = [child.tag.removeprefix(N) for child in node]
    # Report children are checked before removing classified side branches.
    # All other fixed paths have exactly one child; only consumed row collections repeat.
    cardinality = (
        all(name in expected for name in actual)
        if prefix == "Report"
        else (bool(actual) and all(name == expected[0] for name in actual))
        if node.tag.removeprefix(N) in _REPEATED and expected
        else len(actual) == len(expected) and set(actual) == set(expected)
    )
    # Empty completed/pending trade collections are an observed part of S1.
    if (
        node.tag in {N + "Details_Collection", N + "Details2_Collection"}
        and "active_type" not in prefix
    ):
        cardinality = not actual or cardinality
    # The original's caption-only pending table has no collection at all.
    # Frozen S1 supports an explicitly empty trade table; final counted-row
    # comparison still refuses the disappearance of any actual source trade.
    if prefix in {"Report/Tablix2", "Report/Tablix3"} and not actual:
        cardinality = True
    return (
        prefix in allowed
        and cardinality
        and all(
            _visited(
                child,
                prefix + "/" + child.tag.removeprefix(N),
                allowed,
                attrs,
                exact_attrs=exact_attrs,
            )
            for child in node
        )
        and (
            set(node.attrib) == attrs.get(prefix, set())
            if exact_attrs
            else set(node.attrib) <= attrs.get(prefix, set())
        )
        and node.tag.startswith(N)
        and _white(node.text)
        and _white(node.tail)
    )


def draft_structure_exceptions(document: bytes, source: dict) -> list[str] | None:
    """Return classifications only if ALL unparsed content is bounded here.

    Called only after authoritative S1 parsing. None is a hard identity blocker.
    No source hash is supplied by the caller: parse_identity binds original bytes.
    """
    try:
        builder = _OriginalTree()
        root = ET.fromstring(document.decode("utf-8-sig"), parser=ET.XMLParser(target=builder))
    except MyBrokerError:
        return None
    if (
        root.tag != N + "Report"
        or root.attrib
        != {
            "Name": "MyBroker",
            "Textbox5": "Отчет по сделкам и операциям (Отчет брокера)",
            "Textbox6": "Уполномоченное лицо",
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": SCHEMA,
        }
        or builder.namespaces != {"MyBroker", "http://www.w3.org/2001/XMLSchema-instance"}
        or source["document_sha256"] != hashlib.sha256(document).hexdigest()
        or [child.tag for child in root] != [N + outer for outer in SECTIONS]
        or not _white(root.text)
        or not _white(root.tail)
    ):
        return None
    # The original inventory is immutable. A classifier cannot manufacture a
    # different counted source or lend another original its eligible tree.
    for outer, name in SECTIONS.items():
        wrapper = root.find("m:" + outer, NS)
        if wrapper.attrib or len(wrapper) != 1 or wrapper[0].attrib != {"Name": name}:
            return None
        if not all(
            _white(value)
            for value in (wrapper.text, wrapper.tail, wrapper[0].text, wrapper[0].tail)
        ):
            return None
        if source["section_inventory"][name] != sum(1 for _ in wrapper[0].iter()) - 1:
            return None
        if outer in {"Trades3", "Trades4"}:
            # Metadata uses broader str.strip(); DRAFT proof requires XML whitespace.
            if not all(_white(n.text) and _white(n.tail) for n in wrapper.iter()):
                return None
            if len(wrapper[0]) and not _safe(wrapper, outer):
                return None
    row_accounts = {
        r["source_account"] for r in source["positions"] + source["rub_money"] + source["money"]
    }
    row_accounts.update(t["core"]["source_account"] for t in source["trades"])
    if len(row_accounts) != 1 or any(r["currency"] != "RUB" for r in source["money"]):
        return None
    native = [
        (t["section"], t["core"]["source_account"], tuple(t["ids"])) for t in source["trades"]
    ]
    if len(native) != len(set(native)) or any(t["identity"] is None for t in source["trades"]):
        return None
    money_facts = [
        tuple(sorted((k, v) for k, v in row.items() if k != "ordinal")) for row in source["money"]
    ]
    if len(money_facts) != len(set(money_facts)) or any(
        not _number(row["amount"]) for row in source["money"]
    ):
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
            if [n.tag for n in report] not in ([N + "Tablix1"], [N + "Tablix1", N + "Tablix3"]):
                return None
            footers = report.findall("m:Tablix3", NS)
            if footers:
                if len(footers) != 1 or not _shape(footers[0], FOOTER):
                    return None
                report.remove(footers[0])
                exceptions.append("positions_tax_footer_unresolved")
        if outer == "Trades2":
            full_money = any(n.tag != N + "Tablix1" for n in report)
            money_order = (
                "Tablix2",
                "Tablix1",
                "Tablix3",
                "Tablix5",
                "Tablix4",
                "Tablix6",
                "Tablix7",
            )
            if [n.tag for n in report] != [
                N + n for n in money_order if full_money or n == "Tablix1"
            ]:
                return None
            shapes = {
                "Tablix2": (_endpoint(True),),
                "Tablix3": (_endpoint(False),),
                **{tag: (spec,) for tag, spec in BLANKS.items()},
                "Tablix7": SUMMARIES,
            }
            for tag, variants in shapes.items():
                found = report.findall("m:" + tag, NS)
                if found:
                    if len(found) != 1 or not any(_shape(found[0], spec) for spec in variants):
                        return None
                    report.remove(found[0])
                    exceptions.append("money_controls_unresolved")
            tables = report.findall("m:Tablix1", NS)
            if len(tables) != 1:
                return None
            table = tables[0]
            if [n.tag for n in table] != [N + "settlement_date_Collection"] + (
                [N + "Textbox116"] if full_money else []
            ):
                return None
            totals = table.findall("m:Textbox116", NS)
            if totals:
                if len(totals) != 1 or not _shape(totals[0], TOTAL):
                    return None
                table.remove(totals[0])
                exceptions.append("money_controls_unresolved")
            for group in table.findall("m:settlement_date_Collection/m:settlement_date", NS):
                rows = group.findall("m:rn_Collection/m:rn", NS)
                for index, row in enumerate(rows):
                    comment = row.find("m:oper_type/m:comment", NS)
                    if full_money:
                        if [n.tag for n in comment] != [
                            N + n
                            for n in (
                                "money_volume_begin1_Collection",
                                "Textbox95",
                                "Textbox93",
                                "Textbox11",
                            )
                        ]:
                            return None
                        if not _shape(comment[1], DAILY) or not _shape(comment[2], DEBT):
                            return None
                        values = [
                            comment[1][0].get("money_volume"),
                            comment[1][1].get("all_volume"),
                            comment[2].get("debet_volume"),
                        ]
                        if any((v == "") != (index < len(rows) - 1) for v in values):
                            return None
                        comment.remove(comment[1])
                        comment.remove(comment[1])
                        exceptions.append("money_controls_unresolved")
                    elif [n.tag for n in comment] != [
                        N + "Textbox11",
                        N + "money_volume_begin1_Collection",
                    ]:
                        return None
        if outer == "Trades":
            names = [n.tag for n in report]
            if names not in ([N + "Tablix2"], [N + "Tablix3"], [N + "Tablix2", N + "Tablix3"]):
                return None
        allowed = {"Report"}
        for path in _PATHS[outer]:
            parts = ("Report/" + path).split("/")
            allowed.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        if not _visited(report, "Report", allowed, _ATTRS[outer], exact_attrs=outer == "Trades2"):
            return None
    positions = root.findall(
        "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/m:active_type/m:Details_Collection/m:Details",
        NS,
    )
    completed = root.findall("m:Trades/m:Report/m:Tablix2/m:Details_Collection/m:Details", NS)
    pending = root.findall("m:Trades/m:Report/m:Tablix3/m:Details2_Collection/m:Details2", NS)
    amounts = root.findall(
        "m:Trades2/m:Report/m:Tablix1/m:settlement_date_Collection/m:settlement_date/m:rn_Collection/m:rn/m:oper_type/m:comment/m:money_volume_begin1_Collection/m:money_volume_begin1/m:p_code_Collection/m:p_code/m:p_code",
        NS,
    )
    if (
        len(positions) != len(source["positions"]) + len(source["rub_money"])
        or len(completed) != sum(t["section"] == "completed" for t in source["trades"])
        or len(pending) != sum(t["section"] == "pending" for t in source["trades"])
        or len(amounts) != len(source["money"])
    ):
        return None
    return sorted(set(exceptions)) if exceptions else None
