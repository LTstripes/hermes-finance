"""Developer-only Alfa PRO read-only probe CLI. CI must not invoke --live."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hermes_finance.alfa_pro_probe.channels import DEFAULT_ENDPOINT
from hermes_finance.alfa_pro_probe.protocol import (
    DEFAULT_HANDSHAKE_ORIGIN,
    AlfaProbeEndpointError,
    validate_endpoint,
    validate_handshake_origin,
)
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
        help="connection handshake only; no client-data or trading commands",
    )
    parser.add_argument(
        "--connection-state-bus-only",
        action="store_true",
        help=(
            "listen on #ConnectionState.Bus for the overall deadline; "
            "no #Data.Query and no client-data queries"
        ),
    )
    parser.add_argument(
        "--bus-gated-client-read",
        action="store_true",
        help=(
            "wait for AuthStatus=2 on #ConnectionState.Bus, then allowlisted "
            "client-data reads; no ConnectionState #Data.Query"
        ),
    )
    parser.add_argument(
        "--origin",
        default=DEFAULT_HANDSHAKE_ORIGIN,
        help="handshake Origin; must be a non-loopback http(s) web origin",
    )
    parser.add_argument(
        "--id-compare-store",
        help="owner-only keyed ID comparison file; must be outside the repository",
    )
    parser.add_argument("--connect-timeout", type=float, default=CONNECT_TIMEOUT_S)
    parser.add_argument("--read-timeout", type=float, default=READ_TIMEOUT_S)
    parser.add_argument("--deadline", type=float, default=TOTAL_DEADLINE_S)
    args = parser.parse_args(argv)
    if not args.live:
        print("refusing to run without --live")
        return 2
    exclusive_modes = (
        args.origin_handshake_only,
        args.connection_state_bus_only,
        args.bus_gated_client_read,
    )
    if sum(1 for flag in exclusive_modes if flag) > 1:
        print(
            ProbeReport(
                connection="fail",
                authenticated_read="unresolved",
                error="incompatible probe modes",
            ).to_text(),
            end="",
        )
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
    origin = DEFAULT_HANDSHAKE_ORIGIN
    if args.origin_handshake_only:
        try:
            origin = validate_handshake_origin(args.origin)
        except AlfaProbeEndpointError:
            print(
                ProbeReport(
                    connection="fail",
                    foreign_origin_websocket_handshake="unresolved",
                    error="AlfaProbeEndpointError: invalid endpoint or origin",
                ).to_text(),
                end="",
            )
            return 2
    store = Path(args.id_compare_store) if args.id_compare_store else None

    from hermes_finance.alfa_pro_probe.live import LiveConfig, run_live

    report = run_live(
        LiveConfig(
            endpoint=endpoint,
            connect_timeout=_clamp(args.connect_timeout, 0.1, _MAX_CONNECT_TIMEOUT),
            read_timeout=_clamp(args.read_timeout, 0.1, _MAX_READ_TIMEOUT),
            total_deadline=_clamp(args.deadline, 1.0, _MAX_DEADLINE),
            origin_handshake_only=args.origin_handshake_only,
            connection_state_bus_only=args.connection_state_bus_only,
            bus_gated_client_read=args.bus_gated_client_read,
            origin=origin,
            id_compare_store=store,
        )
    )
    print(report.to_text(), end="")
    return 0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
