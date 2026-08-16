"""Deterministic socket/HTTP isolation for R04-08 cold-import checks.

Installed before any application import. Blocks the real network boundary
rather than a module-level constructor alias that may already be bound.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

NETWORK_FORBIDDEN = "external network is forbidden during isolated startup"
_ALLOWED_HOSTS = {
    "127.0.0.1",
    "::1",
    "localhost",
    "testserver",
    "::ffff:127.0.0.1",
}


def _host_of(address: object) -> str | None:
    host: object = address[0] if isinstance(address, tuple) and address else address
    if isinstance(host, bytes):
        host = host.decode()
    if not isinstance(host, str):
        return None
    return host.strip("[]").lower()


def _is_allowed_host(address: object) -> bool:
    host = _host_of(address)
    return host in _ALLOWED_HOSTS


def _contains_forbidden(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if NETWORK_FORBIDDEN in str(current):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def install_network_guard() -> None:
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex
    original_gethostbyaddr = socket.gethostbyaddr

    class GuardedSocket(original_socket):
        def connect(self, address: object, *args: object, **kwargs: object) -> None:
            if not _is_allowed_host(address):
                raise AssertionError(f"{NETWORK_FORBIDDEN}: connect {address!r}")
            return super().connect(address, *args, **kwargs)

        def connect_ex(self, address: object, *args: object, **kwargs: object) -> int:
            if not _is_allowed_host(address):
                raise AssertionError(f"{NETWORK_FORBIDDEN}: connect_ex {address!r}")
            return super().connect_ex(address, *args, **kwargs)

    def guarded_create_connection(address: object, *args: object, **kwargs: object) -> object:
        if not _is_allowed_host(address):
            raise AssertionError(f"{NETWORK_FORBIDDEN}: create_connection {address!r}")
        return original_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if not _is_allowed_host(host):
            raise AssertionError(f"{NETWORK_FORBIDDEN}: getaddrinfo {host!r}")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_gethostbyname(host: object) -> object:
        if not _is_allowed_host(host):
            raise AssertionError(f"{NETWORK_FORBIDDEN}: gethostbyname {host!r}")
        return original_gethostbyname(host)

    def guarded_gethostbyname_ex(host: object) -> object:
        if not _is_allowed_host(host):
            raise AssertionError(f"{NETWORK_FORBIDDEN}: gethostbyname_ex {host!r}")
        return original_gethostbyname_ex(host)

    def guarded_gethostbyaddr(host: object) -> object:
        if not _is_allowed_host(host):
            raise AssertionError(f"{NETWORK_FORBIDDEN}: gethostbyaddr {host!r}")
        return original_gethostbyaddr(host)

    socket.socket = GuardedSocket  # type: ignore[misc]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = guarded_gethostbyname  # type: ignore[assignment]
    socket.gethostbyname_ex = guarded_gethostbyname_ex  # type: ignore[assignment]
    socket.gethostbyaddr = guarded_gethostbyaddr  # type: ignore[assignment]

    import httpx2

    def blocked_http(self: object, request: object) -> object:
        url = getattr(request, "url", request)
        raise AssertionError(f"{NETWORK_FORBIDDEN}: HTTP {url}")

    httpx2.HTTPTransport.handle_request = blocked_http  # type: ignore[method-assign]


def prove_guard_catches_regression() -> None:
    """Fail unless the guard actually intercepts a real outbound attempt."""

    install_network_guard()

    try:
        socket.create_connection(("192.0.2.1", 443), timeout=0.2)
    except AssertionError as error:
        if not _contains_forbidden(error):
            raise
    except BaseException as error:
        raise AssertionError(
            "socket.create_connection was not blocked by the startup network guard"
        ) from error
    else:
        raise AssertionError("socket.create_connection succeeded; guard is a no-op")

    import httpx2

    try:
        with httpx2.Client(timeout=0.2) as client:
            client.get("https://192.0.2.1/")
    except AssertionError as error:
        if not _contains_forbidden(error):
            raise
    except BaseException as error:
        raise AssertionError(
            "httpx HTTP transport was not blocked by the startup network guard"
        ) from error
    else:
        raise AssertionError("httpx request succeeded; guard is a no-op")


def _install_client_construction_guard() -> None:
    from hermes_finance.market_data.moex_iss import MoexIssClient
    from hermes_finance.market_data.t_invest import TInvestClient

    def boom(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError("startup must not construct a market-data client")

    TInvestClient.__init__ = boom  # type: ignore[method-assign]
    MoexIssClient.__init__ = boom  # type: ignore[method-assign]


def run_cold_startup_probe(database_path: Path) -> None:
    import os

    os.environ.pop("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", None)
    install_network_guard()
    _install_client_construction_guard()

    from fastapi.testclient import TestClient

    from hermes_finance.database import create_database
    from hermes_finance.main import create_app
    from hermes_finance.persistence import Base

    database = create_database(database_path)
    Base.metadata.create_all(database.engine)
    try:
        application = create_app(database)
        if application.router.on_startup != []:
            raise AssertionError("startup hooks must stay empty")
        with TestClient(application) as client:
            health = client.get("/api/health")
            months = client.get("/api/months")
            root = client.get("/")
            if health.status_code != 200:
                raise AssertionError(f"health status {health.status_code}")
            if health.json()["status"] != "ok":
                raise AssertionError(f"health body {health.text}")
            if "token" in health.text.lower():
                raise AssertionError("health response mentioned token")
            if months.status_code != 200:
                raise AssertionError(f"months status {months.status_code}")
            if months.json() != []:
                raise AssertionError(f"months body {months.text}")
            if root.status_code not in {200, 404}:
                raise AssertionError(f"root status {root.status_code}")
    finally:
        database.engine.dispose()
    print("ok")


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("usage: startup_network_guard.py prove-guard|probe <database>")
    mode = argv[0]
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    if mode == "prove-guard":
        prove_guard_catches_regression()
        print("guard-ok")
        return 0
    if mode == "probe":
        if len(argv) < 2:
            raise SystemExit("probe requires a database path")
        run_cold_startup_probe(Path(argv[1]))
        return 0
    raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
