"""Developer-only live ISS probe. CI must not invoke this module.

Usage:
    uv run python -m hermes_finance.market_data.probe --live --secid SYNTHS
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime

from hermes_finance.market_data.dto import QuoteFailure, QuoteSuccess
from hermes_finance.market_data.moex_identity import (
    market_identity_from_moex,
    moex_parts_from_identity,
)
from hermes_finance.market_data.moex_iss import MoexIssClient
from hermes_finance.market_data.moscow import MOSCOW_TZ


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Optional live MOEX ISS probe. Does not apply quotes or write a database."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="required opt-in; refuse to touch the network without this flag",
    )
    parser.add_argument("--query")
    parser.add_argument("--secid")
    parser.add_argument("--isin")
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument("--engine")
    parser.add_argument("--market")
    parser.add_argument("--boardid")
    args = parser.parse_args(argv)
    if not args.live:
        print("refusing to run without --live")
        return 2

    target = args.target_date or datetime.now(MOSCOW_TZ).date()
    with MoexIssClient() as client:
        if args.engine and args.market and args.boardid and args.secid:
            result = client.fetch_quote(
                market_identity_from_moex(
                    engine=args.engine,
                    market=args.market,
                    boardid=args.boardid,
                    secid=args.secid,
                    isin=args.isin,
                ),
                target,
            )
            print(_format_quote(result))
            return 0 if isinstance(result, QuoteSuccess) else 1

        discovered = client.discover_candidates(
            query=args.query,
            provider_instrument_id=args.secid,
            isin=args.isin,
        )
        payload = {
            "status": discovered.status.value,
            "message": discovered.message,
            "candidates": [
                {
                    "provider": item.identity.provider,
                    "provider_instrument_id": item.identity.provider_instrument_id,
                    "provider_venue_id": item.identity.provider_venue_id,
                    "isin": item.identity.isin,
                    "instrument_kind": item.instrument_kind.value,
                }
                for item in discovered.candidates
            ],
            "rejected": [
                {
                    "provider_instrument_id": item.provider_instrument_id,
                    "candidate_isin": item.candidate_isin,
                    "expected_isin": item.expected_isin,
                    "reason": item.reason,
                }
                for item in discovered.rejected
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if discovered.candidates else 1


def _format_quote(result: QuoteSuccess | QuoteFailure) -> str:
    if isinstance(result, QuoteFailure):
        return json.dumps(
            {
                "status": result.status.value,
                "message": result.message,
            },
            ensure_ascii=False,
            indent=2,
        )
    parts = moex_parts_from_identity(result.identity)
    return json.dumps(
        {
            "status": result.status.value,
            "provider": result.identity.provider,
            "provider_instrument_id": result.identity.provider_instrument_id,
            "provider_venue_id": result.identity.provider_venue_id,
            "engine": parts.engine,
            "market": parts.market,
            "boardid": parts.boardid,
            "secid": parts.secid,
            "instrument_kind": result.instrument_kind.value,
            "raw_price": result.raw_price,
            "raw_price_basis": result.raw_price_basis.value,
            "proposed_price_kopecks": result.proposed_price_kopecks,
            "price_date": result.price_date.isoformat(),
            "quote_kind": result.quote_kind.value,
            "freshness_status": result.freshness_status.value,
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    raise SystemExit(main())
