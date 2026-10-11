"""Versioned metadata envelope; the accepted S1 v2 shape is never changed.

Field authority: #771 Integrator manifest 6106946806. Positions do not prove
security denomination. Trade currency and RUB cash cannot fill that absence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import NS, parse_mybroker, single

METADATA_PARSER = "mybroker-identity-v1"
ASSET_TYPES = {"Акции": "stock", "Облигации": "bond"}
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", re.ASCII)


def parse_identity(document: bytes, filename: str) -> dict:
    source = parse_mybroker(document, filename)  # family, bounds, rows, unchanged original hash
    root = ET.fromstring(document.decode("utf-8-sig"))
    conflicts = set(source["syntax_blockers"]) & {"unparsed_source_rows", "unknown_section"}
    conflicts.update(source["endpoint_conflicts"])
    if "position_row_unclassified" in source["endpoint_blockers"]:
        conflicts.add("position_row_unclassified")
    observations = defaultdict(list)
    position_aliases = []
    row_accounts = {r["source_account"] for r in source["rub_money"] + source["money"]}
    for ordinal, row in enumerate(
        root.findall(
            "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
            "m:active_type/m:Details_Collection/m:Details",
            NS,
        )
    ):
        isin = single(row.get("ISIN1"), optional=True)
        if isin is None:
            continue  # currency/unclassified already guarded by S1
        account = single(row.get("acc_code"))
        kind = single(row.get("active_type"), optional=True)
        name = single(row.get("active_name"), optional=True)
        observations[isin].append(
            {
                "section": "positions",
                "ordinal": ordinal,
                "source_account": account,
                "isin": isin,
                "source_type": kind,
                "instrument_type": ASSET_TYPES.get(kind),
                "source_name": name,
                "place": single(row.get("place"), optional=True),
            }
        )
        position_aliases.append({"source_account": account, "isin": isin})
        row_accounts.add(account)
    for pending, path in (
        (False, "m:Trades/m:Report/m:Tablix2/m:Details_Collection/m:Details"),
        (True, "m:Trades/m:Report/m:Tablix3/m:Details2_Collection/m:Details2"),
    ):
        trades = [
            t for t in source["trades"] if t["section"] == ("pending" if pending else "completed")
        ]
        for row, trade in zip(root.findall(path, NS), trades, strict=True):
            isin, account = trade["core"]["isin"], trade["core"]["source_account"]
            row_currency = None if pending else single(row.get("Textbox14"), optional=True)
            if row_currency is not None and row_currency != trade["core"]["currency"]:
                conflicts.add("trade_currency_observation_conflict")
            # Pending metadata field names are not in the accepted manifest.
            observations[isin].append(
                {
                    "section": trade["section"],
                    "ordinal": trade["ordinal"],
                    "isin": isin,
                    "source_account": account,
                    "source_name": None if pending else single(row.get("p_name"), optional=True),
                    "settlement_currency": trade["core"]["currency"],
                    "row_currency_observation": row_currency,
                }
            )
            row_accounts.add(account)
            if trade["repo_observed"]:
                conflicts.add("repo_identity_unsupported")
            if trade["core"]["currency"] != "RUB":
                conflicts.add("settlement_currency_unsupported")
    instruments = []
    for isin, rows in sorted(observations.items()):
        gaps = []
        if not ISIN.fullmatch(isin):
            conflicts.add("instrument_isin_invalid")
        positions = [r for r in rows if r["section"] == "positions"]
        types = {r["instrument_type"] for r in positions}
        if not positions or types == {None}:
            gaps.append("instrument_type_unproven")
        elif None in types or len(types) != 1:
            conflicts.add("instrument_type_conflict")
        if any(r["source_type"] is not None and r["instrument_type"] is None for r in positions):
            conflicts.add("instrument_type_unsupported")
        for row in rows:
            if row["section"] != "positions" and not any(
                p["source_account"] == row["source_account"] for p in positions
            ):
                gaps.append("instrument_type_unproven")
        names = {r["source_name"] for r in positions}
        if len(names) > 1:
            conflicts.add("instrument_name_ambiguous")
        name = next(iter(names)) if len(names) == 1 else None
        if name is None:
            gaps.append("instrument_name_unproven")
        instruments.append(
            {
                "isin": isin,
                "instrument_type": next(iter(types)) if len(types) == 1 else None,
                "source_name": name,
                "currency": None,
                "currency_basis": "unproven",
                "evidence_gaps": sorted(set(gaps)),
                "observations": rows,
            }
        )
    return {
        "provider": source["provider"],
        "source_parser": source["parser"],
        "metadata_parser": METADATA_PARSER,
        "document_sha256": source["document_sha256"],
        "filename_account": source["filename_account"],
        "covered_from": source["covered_from"],
        "covered_to": source["covered_to"],
        "source_accounts": sorted(row_accounts | {source["filename_account"]}),
        "row_accounts": sorted(row_accounts),
        "position_aliases": position_aliases,
        "instruments": instruments,
        "conflicts": sorted(conflicts),
        "source_warnings": source["syntax_blockers"],
    }
