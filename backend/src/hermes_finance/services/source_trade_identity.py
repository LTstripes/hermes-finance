"""Read-only identity for the already recognized single-B-ID REPO grammar.

The partner reference is never a second economic trade ID. Frozen parser facts,
financial receipts and REPO cash/quantity authority remain unchanged.
"""

import re
from collections import Counter

from hermes_finance.statement_import.mybroker import NS, PROVIDER, digest
from hermes_finance.statement_import.mybroker_return_structure import _inventory_tree


def repo_return_identities(view):
    """Return ordinal -> (projection identity, partner/leg signature).

    Require the original inventory and normalized row to agree. Repeated B IDs
    inside one original are ambiguous even if their values happen to agree.
    """
    document = view["document"]
    if document.get("provider") != PROVIDER or document.get("parser") != "mybroker-s1-v2":
        return {}
    if not any(
        t.get("repo_observed") and len(t.get("ids", [])) == 1 for t in document.get("trades", [])
    ):
        return {}
    try:
        references = {}
        root = _inventory_tree(view["observations"], references=references)
        reports = root.findall("m:Trades/m:Report", NS)
        if root.tag != "{MyBroker}Report" or len(reports) != 1:
            return {}
        nodes = reports[0].findall("m:Tablix2/m:Details_Collection/m:Details", NS)
        trades = [t for t in document.get("trades", []) if t["section"] == "completed"]
        if len(nodes) != len(trades) or {t["ordinal"] for t in trades} != set(range(len(nodes))):
            return {}
        counts = Counter((t["core"]["source_account"], t["ids"][0]) for t in trades if t.get("ids"))
        by_ordinal = {t["ordinal"]: t for t in trades}
        result = {}
        for ordinal, node in enumerate(nodes):
            trade, native = by_ordinal[ordinal], references[id(node)]
            own, partner = native.get("trade_no", ""), native.get("repo_no", "")
            account, isin = trade["core"]["source_account"], trade["core"]["isin"]
            if (
                trade.get("state") == "settled"
                and trade.get("identity") is None
                and trade.get("repo_observed") is True
                and trade.get("ids") == [own]
                and re.fullmatch(r"B[0-9]{1,127}", own)
                and re.fullmatch(r"B[0-9]{1,127}", partner)
                and own != partner
                and counts[(account, own)] == 1
                and native.get("acc_code") == account
                and native.get("isin_reg") == isin
                and all(
                    node.get(field) == digest(native[field])
                    for field in ("trade_no", "repo_no", "acc_code", "isin_reg")
                )
                and node.get("comment") in {digest("репо ч.1"), digest("репо ч.2")}
            ):
                result[ordinal] = (
                    "repo:" + digest([PROVIDER, account, own]),
                    (partner, node.get("comment")),
                )
        return result
    except (ValueError, TypeError, KeyError, AttributeError):
        return {}
