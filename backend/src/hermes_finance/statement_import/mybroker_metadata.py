"""Exact #789 non-economic trees. Evidence only; no S1 or Close authority."""

from __future__ import annotations

import re
from datetime import datetime
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import SECTIONS, parse_mybroker

METADATA_PARSER = "mybroker-section-metadata-v1"
START = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4} [0-9]{2}:[0-9]{2}", re.ASCII)


def _node(node: ET.Element, tag: str, attrs: dict, children: int) -> bool:
    return (
        node.tag == f"{{MyBroker}}{tag}"
        and node.attrib == attrs
        and len(node) == children
        and not (node.text or "").strip()
        and not (node.tail or "").strip()
    )


def _safe(wrapper: ET.Element, outer: str) -> bool:
    if not _node(wrapper, outer, {}, 1):
        return False
    report = wrapper[0]
    if not _node(report, "Report", {"Name": SECTIONS[outer]}, 1):
        return False
    table = report[0]
    if outer == "Trades3":
        return _node(table, "Tablix1", {}, 0)
    if not _node(table, "Tablix1", {"Textbox4": "Подключен"}, 1):
        return False
    collection = table[0]
    if not _node(collection, "Details_Collection", {}, 1):
        return False
    details = collection[0]
    start = details.get("sys_start_time", "")
    if not _node(details, "Details", {"sys_start_time": start, "sys_end_time": "-"}, 0):
        return False
    if not START.fullmatch(start):
        return False
    try:
        datetime.strptime(start, "%d.%m.%Y %H:%M")
    except ValueError:
        return False
    return True


def parse_section_metadata(document: bytes, filename: str) -> dict:
    """Reparse original bytes with S1 family/bounds, retain all source blockers.

    Frozen Money grammar is sufficient for syntax/inventory; this envelope never
    owns Money linkage or upgrades accepted receipts. Comments/PIs are preserved
    in this second tree so they cannot disappear into an apparently safe shape.
    Connection times are validated only and never returned as period/event facts.
    """
    source = parse_mybroker(document, filename, money_linkage_version=None)
    root = ET.fromstring(
        document.decode("utf-8-sig"),
        parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)),
    )
    sections = []
    for outer in ("Trades3", "Trades4"):
        # Include foreign namespace lookalikes in cardinality checks.
        wrappers = [
            child
            for child in root
            if isinstance(child.tag, str) and child.tag.rsplit("}", 1)[-1] == outer
        ]
        safe = len(wrappers) == 1 and _safe(wrappers[0], outer)
        sections.append(
            {
                "section": SECTIONS[outer],
                "status": "READY_SAFE_STRUCTURE" if safe else "BLOCKED",
                "pattern": ("empty_transfers" if outer == "Trades3" else "ufsr_open_connection")
                if safe
                else None,
                "raw_inventory": source["section_inventory"][SECTIONS[outer]],
                "derived_movements": 0,
                "period_scope": "unknown",
            }
        )
    return {
        "provider": source["provider"],
        "source_parser": source["parser"],
        "metadata_parser": METADATA_PARSER,
        "document_sha256": source["document_sha256"],
        "sections": sections,
        "source_warnings": source["syntax_blockers"],
        "coverage_state": "unknown",
    }
