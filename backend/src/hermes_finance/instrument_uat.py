"""Explicit offline instrument UAT. No standard app startup, migrator or provider."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import socket
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

from hermes_finance import scratch_preflight as scratch
from hermes_finance.api import (
    accounts,
    instrument_cash_income,
    instrument_eod_observations,
    instrument_trades,
    instrument_what_if,
    instruments,
)
from hermes_finance.security import LocalhostSecurityMiddleware

KIND = "instrument_uat_scratch"
PORT = 18868
SELECTORS = {"/api/accounts", "/api/instruments"}
READERS = {
    "/api/instruments/{instrument_id}/cash-income",
    "/api/instruments/{instrument_id}/eod-observations",
    "/api/instruments/{instrument_id}/known-trades",
    "/api/instruments/{instrument_id}/conditional-return",
}
READER_PATH = re.compile(
    r"/api/instruments/[1-9][0-9]*/(cash-income|eod-observations|known-trades|conditional-return)"
)


def readiness_proof(token, document, pid, started):
    message = "|".join(
        str(v)
        for v in (
            KIND,
            PORT,
            pid,
            started,
            document["checkout_sha"],
            document["database_identity"],
            document["snapshot_sha256"],
        )
    )
    return hmac.new(token.encode("ascii"), message.encode("ascii"), hashlib.sha256).hexdigest()


def static_bundle(dist: Path, stack: ExitStack):
    """Pin only the built UAT entry's dependency closure, never the main SPA."""
    manifest = dist / ".vite/manifest.json"
    stack.enter_context(scratch._hold_snapshot(manifest))
    chunks = json.loads(manifest.read_text(encoding="utf-8"))
    paths, visited = {"instrument-uat.html"}, set()

    def visit(key):
        if key in visited:
            return
        visited.add(key)
        chunk = chunks[key]
        paths.update([chunk["file"], *chunk.get("css", []), *chunk.get("assets", [])])
        for dependency in [*chunk.get("imports", []), *chunk.get("dynamicImports", [])]:
            visit(dependency)

    visit("instrument-uat.html")
    result, fingerprints = {}, {manifest: scratch._digest(manifest)}
    for relative in sorted(paths):
        # Vite output only: no arbitrary files, absolute paths, traversal or maps.
        if ".." in relative or (
            relative != "instrument-uat.html"
            and not re.fullmatch(
                r"assets/[A-Za-z0-9_][A-Za-z0-9_.-]*\.(js|css|woff2?|png|svg)", relative
            )
        ):
            raise scratch.ScratchError("uat_static_manifest_invalid")
        path = scratch._path(str(dist / relative))
        stack.enter_context(scratch._hold_snapshot(path))
        fingerprints[path] = scratch._digest(path)
        result["/" if relative == "instrument-uat.html" else "/" + relative] = (
            path.read_bytes(),
            mimetypes.guess_type(relative)[0] or "application/octet-stream",
        )
    return result, fingerprints


def create_reader(database, document, token, static, check_binding):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)
    app.state.database = database
    started = time.time_ns()
    failed = False

    def safe_error(status):
        return JSONResponse({"detail": "uat_request_unavailable"}, status_code=status)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return safe_error(error.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return safe_error(422)

    # Reuse actual APIRoutes (including response DTO/dependency behavior), but
    # register exactly six GET routes; never attach a CRUD/provider router.
    for router in (
        accounts.router,
        instruments.router,
        instrument_cash_income.router,
        instrument_eod_observations.router,
        instrument_trades.router,
        instrument_what_if.router,
    ):
        for route in router.routes:
            if (
                isinstance(route, APIRoute)
                and route.path in SELECTORS | READERS
                and route.methods == {"GET"}
            ):
                app.router.routes.append(route)

    @app.get("/api/health")
    def health(request: Request):
        public = {"status": "ok", "mode": KIND}
        if hmac.compare_digest(request.headers.get("X-Hermes-Uat-Token", ""), token):
            public.update(
                pid=os.getpid(),
                process_started_ns=started,
                binding=readiness_proof(token, document, os.getpid(), started),
            )
        return public

    @app.get("/{path:path}")
    def asset(path: str, request: Request):
        payload = static.get(request.url.path)
        if payload is None:
            return safe_error(404)
        return Response(payload[0], media_type=payload[1])

    app.add_middleware(LocalhostSecurityMiddleware)

    @app.middleware("http")
    async def containment(request: Request, call_next):
        nonlocal failed
        try:
            host = request.headers.get("host", "")
            if host not in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}:
                response = safe_error(400)
            elif (
                request.headers.get("origin") not in {None, "http://" + host}
                or request.headers.get("sec-fetch-site") == "cross-site"
            ):
                response = safe_error(403)
            elif request.method != "GET":
                response = safe_error(405)
            elif request.url.path not in static.keys() | SELECTORS | {
                "/api/health"
            } and not READER_PATH.fullmatch(request.url.path):
                response = safe_error(404)
            elif failed:
                response = safe_error(503)
            else:
                # A detected failure latches for this process: A→B→A cannot
                # revive an old binding. Only an explicit new Start can do so.
                try:
                    check_binding()
                except Exception:
                    failed = True
                    raise
                response = await call_next(request)
        except Exception:
            failed = True
            response = safe_error(503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
        )
        return response

    return app


@contextmanager
def reader_runtime(manifest: Path, token: str):
    if not scratch.HEX64.fullmatch(token):
        raise scratch.ScratchError("uat_readiness_token_invalid")
    with ExitStack() as stack:
        manifest = scratch._path(str(manifest))
        stack.enter_context(scratch._hold_snapshot(manifest))
        document = scratch.validate_manifest(manifest, expected_kind=KIND)
        pinned = [
            Path(document["database"]),
            Path(document["runtime_inventory"]),
            Path(document["database"]).parent / ".hermes-data-identity.json",
        ]
        for path in pinned:
            stack.enter_context(scratch._hold_snapshot(path))
        # Close the validation-to-pinning race for config and snapshot bindings.
        if scratch.validate_manifest(manifest, expected_kind=KIND) != document:
            raise scratch.ScratchError("uat_manifest_changed")
        static, fingerprints = static_bundle(Path(document["checkout"]) / "frontend/dist", stack)
        # Ignored production-dist bytes must still match the prepared marker
        # AFTER pinning. Do not adopt replaced bytes during the validation gap.
        scratch._prepared(Path(document["checkout"]))
        fingerprints.update({p: scratch._digest(p) for p in [manifest, *pinned[1:]]})

        def check():
            scratch._check_snapshot(document)
            for path, digest in fingerprints.items():
                if scratch._digest(path) != digest:
                    raise scratch.ScratchError("uat_binding_changed")
            scratch.safety._validate_recovery_checkout(
                Path(document["checkout"]),
                Path(document["control_checkout"]),
                document["checkout_sha"],
            )

        check()
        database = scratch._read_database(document)
        try:
            yield create_reader(database, document, token, static, check)
        finally:
            database.engine.dispose()
            check()


def main(arguments=None):
    parser = scratch._Parser(add_help=False)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--readiness-token", required=True)
    parser.add_argument("--check", action="store_true")
    try:
        args = parser.parse_args(arguments)
        if sys.platform != "win32":
            raise scratch.ScratchError("uat_windows_required")
        with reader_runtime(args.manifest, args.readiness_token) as app:
            if args.check:
                return
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(("127.0.0.1", PORT))
                listener.listen(128)
                uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical")).run(
                    sockets=[listener]
                )
    except (Exception, KeyboardInterrupt):
        print("instrument_uat_failed_closed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
