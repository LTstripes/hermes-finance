"""Developer-only Alfa PRO read-only probe CLI. CI must not invoke --live."""

from __future__ import annotations

import argparse
import sys

from hermes_finance.alfa_pro_probe.channels import DEFAULT_ENDPOINT
from hermes_finance.alfa_pro_probe.protocol import AlfaProbeEndpointError, validate_endpoint
from hermes_finance.alfa_pro_probe.reader import CONNECT_TIMEOUT_S, READ_TIMEOUT_S, TOTAL_DEADLINE_S
from hermes_finance.alfa_pro_probe.report import ProbeReport

_MAX_CONNECT_TIMEOUT = 15.0
_MAX_READ_TIMEOUT = 10.0
_MAX_DEADLINE = 60.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Optional live Alfa PRO read-only probe. Loopback-only. "
            "Does not trade, sign, persist, or write Hermes database files."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="required opt-in; refuse to touch the network without this flag",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help="documented loopback router; non-loopback hosts are rejected",
    )
    parser.add_argument(
        "--origin-handshake-only",
        action="store_true",
        help="connection handshake with a benign local Origin; no client-data queries",
    )
    parser.add_argument("--connect-timeout", type=float, default=CONNECT_TIMEOUT_S)
    parser.add_argument("--read-timeout", type=float, default=READ_TIMEOUT_S)
    parser.add_argument("--deadline", type=float, default=TOTAL_DEADLINE_S)
    args = parser.parse_args(argv)
    if not args.live:
        print("refusing to run without --live")
        return 2
    try:
        endpoint = validate_endpoint(args.endpoint)
    except AlfaProbeEndpointError as exc:
        print(
            ProbeReport(
                connection="fail", error="AlfaProbeEndpointError: invalid endpoint"
            ).to_text()
        )
        print(f"endpoint_rejected: {type(exc).__name__}", file=sys.stderr)
        return 2

    from hermes_finance.alfa_pro_probe.live import LiveConfig, run_live

    report = run_live(
        LiveConfig(
            endpoint=endpoint,
            connect_timeout=_clamp(args.connect_timeout, 0.1, _MAX_CONNECT_TIMEOUT),
            read_timeout=_clamp(args.read_timeout, 0.1, _MAX_READ_TIMEOUT),
            total_deadline=_clamp(args.deadline, 1.0, _MAX_DEADLINE),
            origin_handshake_only=args.origin_handshake_only,
        )
    )
    print(report.to_text(), end="")
    return 0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
