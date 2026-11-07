"""Owner-local coverage check. Never schedule against private data in CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]


def validate_paths(database: Path, out: Path) -> tuple[Path, Path]:
    database, out = database.resolve(), out.resolve()
    if out == REPOSITORY or REPOSITORY in out.parents:
        raise ValueError("Output must be outside the repository")
    if not database.is_file():
        raise ValueError("Database must be an existing file")
    if out.exists() and not out.is_dir():
        raise ValueError("Output must be a directory")
    return database, out


def _present(metric):
    return bool(metric) and metric.get("value") is not None


def summarize(session):
    from hermes_finance.services.returns_overall import (
        read_clean_instrument_card,
        read_clean_overall,
    )

    overview = read_clean_overall(session)
    rows = []
    for instrument in overview["instruments"]:
        card = read_clean_instrument_card(session, instrument["isin"])
        for account in card["accounts"]:
            clean = account.get("clean") or {}
            pnl = clean.get("pnl") or {}
            purchases = account.get("purchases")
            with_result = (
                sum(p["price_result_kopecks"] is not None for p in purchases)
                if purchases is not None
                else None
            )
            quantity = (account.get("detail") or {}).get("closing_quantity")
            from decimal import Decimal

            rows.append(
                {
                    "key": hashlib.sha256(
                        json.dumps([instrument["isin"], account["scope"]]).encode()
                    ).hexdigest(),
                    "kind": card["kind"],
                    "full_result": _present(pnl)
                    and pnl.get("status") in {"supported", "provisional"}
                    and "source_account_identity_mapping_conflict" not in account["reason_codes"],
                    "rate_exists": _present(clean.get("modified_dietz")),
                    "known_result_exists": _present(clean.get("known_result")),
                    "closing_value_exists": _present(clean.get("closing_value")),
                    "open_position": None if quantity is None else Decimal(quantity) != 0,
                    "purchases_with_result": with_result,
                    "purchases_without_result": None
                    if purchases is None
                    else len(purchases) - with_result,
                    "pnl_reason_codes": pnl.get("reason_codes", []),
                }
            )
    rows.sort(key=lambda row: row["key"])
    return {
        "schema_version": 1,
        "rows": rows,
        "totals": {
            "rows_with_full_result": sum(r["full_result"] for r in rows),
            "open_positions_with_full_result": sum(
                r["full_result"] and r["open_position"] is True for r in rows
            ),
            "purchases_with_result": sum(r["purchases_with_result"] or 0 for r in rows),
            "rows_with_unknown_purchases": sum(r["purchases_with_result"] is None for r in rows),
        },
    }


def differences(previous, current):
    old = {r["key"]: r for r in previous["rows"]}
    new = {r["key"]: r for r in current["rows"]}
    lines = []
    for index, key in enumerate(sorted(old.keys() | new.keys()), 1):
        before, after = old.get(key, {}), new.get(key, {})
        for field in ("full_result", "purchases_with_result", "purchases_without_result"):
            if before.get(field) != after.get(field):
                lines.append(f"row {index}: {field}: {before.get(field)} -> {after.get(field)}")
    return lines


def run(database, out, *, compare=None, keep_copy=False):
    database, out = validate_paths(database, out)
    previous = json.loads(compare.read_text(encoding="utf-8")) if compare else None
    out.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="returns-", suffix=".sqlite", dir=out)
    import os

    os.close(descriptor)
    copy = Path(name)
    engine = None
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(copy)) as target:
                source.backup(target)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from hermes_finance.settings import Settings

        engine = create_engine(
            "sqlite://", creator=lambda: sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True)
        )
        with Session(engine) as session:
            session.info["reviewed_bond_valuation_path"] = Settings().reviewed_bond_valuation_path
            summary = summarize(session)
        # Exclusive creation avoids accidentally overwriting the input or previous summary.
        with (out / "summary.json").open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2)
        if previous is not None:
            for line in differences(previous, summary):
                print(line)
        else:
            for key, value in summary["totals"].items():
                print(f"{key}: {value}")
        return summary
    finally:
        if engine is not None:
            engine.dispose()
        if not keep_copy:
            copy.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--keep-copy", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(args.database, args.out, compare=args.compare, keep_copy=args.keep_copy)
    except Exception:
        # Exceptions from source readers can contain private values and paths.
        print("Returns check failed; verify inputs, schema and output directory locally.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
