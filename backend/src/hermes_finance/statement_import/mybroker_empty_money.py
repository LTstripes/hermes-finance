"""Original-bound #802 observation only; never financial or section authority."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import SCHEMA, SECTIONS, MyBrokerError, parse_mybroker

DIAGNOSTIC_PARSER = "mybroker-empty-money-layout-v1"
NAMESPACE = "MyBroker"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
MONEY_CHILDREN = ("Tablix2", "Tablix1", "Tablix3", "Tablix5", "Tablix4", "Tablix6", "Tablix7")
TREE_PATH = "Report/Trades2/Report[@Name='3_BrokerMoneyMove']/Tablix5"


class _OriginalTree(ET.TreeBuilder):
    """Do not silently discard comments/PIs, including outside the root."""

    def __init__(self):
        super().__init__()
        self.started = False
        self.namespaces = set()

    def start(self, tag, attrs):
        self.started = True
        return super().start(tag, attrs)

    def start_ns(self, prefix, uri):
        # Only the root's two source-family declarations; no nested rebinding.
        if self.started or uri not in (NAMESPACE, XSI) or uri in self.namespaces:
            raise MyBrokerError("diagnostic_namespace_invalid")
        self.namespaces.add(uri)

    def comment(self, text):
        raise MyBrokerError("diagnostic_comment_or_pi")

    def pi(self, target, text):
        raise MyBrokerError("diagnostic_comment_or_pi")


def _white(text: str | None) -> bool:
    return all(character in " \t\r\n" for character in text or "")


def _node(node: ET.Element, tag: str, attrs: dict, children: tuple[str, ...]) -> bool:
    return (
        node.tag == f"{{{NAMESPACE}}}{tag}"
        and node.attrib == attrs
        and [child.tag for child in node] == [f"{{{NAMESPACE}}}{name}" for name in children]
        and _white(node.text)
        and _white(node.tail)
        # Child tails are character data of this parent, between siblings.
        and all(_white(child.tail) for child in node)
    )


def _exact(root: ET.Element) -> bool:
    if not _node(
        root,
        "Report",
        {
            "Name": "MyBroker",
            "Textbox5": "Отчет по сделкам и операциям (Отчет брокера)",
            "Textbox6": "Уполномоченное лицо",
            f"{{{XSI}}}schemaLocation": SCHEMA,
        },
        tuple(SECTIONS),
    ):
        return False
    wrapper = root[2]
    if not _node(wrapper, "Trades2", {}, ("Report",)):
        return False
    report = wrapper[0]
    if not _node(report, "Report", {"Name": SECTIONS["Trades2"]}, MONEY_CHILDREN):
        return False
    # An extra/moved/foreign lookalike anywhere must not borrow this observation.
    if sum(node.tag.rsplit("}", 1)[-1] == "Tablix5" for node in root.iter()) != 1:
        return False
    table = report[3]
    if not _node(table, "Tablix5", {}, ("Textbox3",)):
        return False
    textbox = table[0]
    if not _node(textbox, "Textbox3", {}, ("Textbox61",)):
        return False
    leaves = textbox[0]
    return (
        _node(leaves, "Textbox61", {}, ("Textbox46", "Textbox47"))
        and _node(leaves[0], "Textbox46", {}, ())
        and _node(leaves[1], "Textbox47", {}, ())
    )


def parse_empty_money_layout(
    document: bytes, filename: str, *, expected_document_sha256: str
) -> dict:
    """Observe one original only, with frozen S1 family/size/DTD/depth guards.

    Invalid S1 inputs retain their existing sanitized errors. A valid S1 source
    with any diagnostic mismatch is BLOCKED as a whole. Hashes always cover the
    supplied original bytes, never a serialization of the diagnostic tree.
    No DB/session, receipt dispatch, normalization or economic inference occurs.
    """
    source = parse_mybroker(document, filename, money_linkage_version=None)
    exact = False
    if source["document_sha256"] == expected_document_sha256:
        try:
            root = ET.fromstring(
                document.decode("utf-8-sig"), parser=ET.XMLParser(target=_OriginalTree())
            )
            exact = _exact(root)
        except MyBrokerError:
            pass
    return {
        "diagnostic_parser": DIAGNOSTIC_PARSER,
        "provider": source["provider"],
        "source_parser": source["parser"],
        "document_sha256": source["document_sha256"],
        "source_scope": {
            key: source[key] for key in ("filename_account", "covered_from", "covered_to")
        },
        "section": SECTIONS["Trades2"],
        "status": "EXACT_EMPTY_TREE_OBSERVED" if exact else "BLOCKED",
        "path": TREE_PATH if exact else None,
        "observed_nodes": 5 if exact else None,
        "authority": "none",
        "derived_movements": 0,
        "coverage_state": "unknown",
        "source_warnings": source["syntax_blockers"],
    }
