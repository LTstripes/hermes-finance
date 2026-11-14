"""Bounded reuse of pure GET projections, identified by the entire SQL snapshot.

No writer hooks, connection-local data_version, timestamps or row counts stand
in for database contents. Unsupported/large databases and uncertain external
inputs simply use the original reader. Never apply this to commands, form
tokens, backup/readiness state or responses containing a generation timestamp.
"""

import hashlib
import inspect
import json
import pickle
import sqlite3
from collections import OrderedDict
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

from fastapi import Request, Response

from hermes_finance import __version__
from hermes_finance.services.source_monthly_returns import source_read_snapshot
from hermes_finance.source_proof_file import file_incarnation

MAX_DATABASE_BYTES = 128 * 1024 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 128
_entries = OrderedDict()
_lock = RLock()
_size = 0


def _file_signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        getattr(info, "st_birthtime_ns", None),
    )


def _external_key(session):
    from hermes_finance.services import source_return_proofs
    from hermes_finance.services.source_investment_proofs import SEMANTICS_REVISION
    from hermes_finance.statement_import import mybroker, mybroker_return_structure

    connection = session.connection()
    filename = connection.engine.url.database
    if not filename or filename == ":memory:":
        return None
    physical = file_incarnation(Path(filename))
    if not physical or connection.info.get("source_proof_incarnation") != physical:
        return None
    configured = session.info.get("reviewed_bond_valuation_path")
    valuation = None
    if configured is not None:
        path = Path(configured)
        if not path.is_absolute() or path.is_symlink():
            return None
        before = path.stat()
        if before.st_nlink != 1 or not 0 < before.st_size <= 256 * 1024:
            return None
        raw = path.read_bytes()
        after = path.stat()
        if _file_signature(before) != _file_signature(after):
            return None
        valuation = (str(path), _file_signature(before), hashlib.sha256(raw).digest())
    # These file bytes participate in legacy proof currentness independently of
    # the running module version. A development edit must not revive an old hit.
    code = tuple(
        hashlib.sha256(Path(module.__file__).read_bytes()).digest()
        for module in (source_return_proofs, mybroker, mybroker_return_structure)
    )
    return (
        str(Path(filename).resolve()),
        physical,
        __version__,
        SEMANTICS_REVISION,
        code,
        valuation,
        date.today(),
        datetime.now(ZoneInfo("Europe/Moscow")).date(),
        session.info.get("source_intake_epoch"),
        json.dumps(session.info.get("returns_account_display_names", {}), sort_keys=True),
    )


def _snapshot_key(session):
    connection = session.connection()
    driver = connection.connection.driver_connection
    if connection.dialect.name != "sqlite" or not hasattr(driver, "serialize"):
        return None
    # Pin the deferred transaction BEFORE serialize; include WAL-visible pages.
    connection.exec_driver_sql("SELECT count(*) FROM sqlite_schema").scalar()
    pages = connection.exec_driver_sql("PRAGMA page_count").scalar()
    size = connection.exec_driver_sql("PRAGMA page_size").scalar()
    if pages * size > MAX_DATABASE_BYTES:
        return None
    external = _external_key(session)
    if external is None:
        return None
    return external, hashlib.sha256(driver.serialize()).digest()


def cached_read_endpoint(function):
    """Cache an explicitly selected pure endpoint after dependency validation.

    Each hit still acquires a new coherent committed snapshot and verifies its
    complete contents, file incarnation and external valuation/code inputs.
    Dependencies (including selection validation) run normally on every GET.
    """
    signature = inspect.signature(function, eval_str=True)

    @wraps(function)
    def wrapped(*args, **kwargs):
        global _size
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        session = arguments.arguments["session"]
        values = {}
        for name, value in arguments.arguments.items():
            if name == "session":
                continue
            if isinstance(value, Response):
                value.headers["Cache-Control"] = "no-store"
            elif isinstance(value, Request):
                values[name] = list(value.query_params.multi_items())
            else:
                values[name] = value
        selection = json.dumps(values, sort_keys=True, default=str)
        with source_read_snapshot(session):
            try:
                snapshot = _snapshot_key(session)
            except (OSError, ValueError, sqlite3.Error):
                snapshot = None
            if snapshot is None:
                return function(*args, **kwargs)
            key = (function.__module__, function.__name__, selection, snapshot)
            with _lock:
                encoded = _entries.get(key)
                if encoded is not None:
                    _entries.move_to_end(key)
            if encoded is not None:
                return pickle.loads(encoded)
            result = function(*args, **kwargs)
            # Month readers intentionally contain optional-explanation errors.
            # Preserve their next-read recovery instead of memoizing a fallback.
            complete = not values.get("include_capital_change", False) or (
                getattr(getattr(result, "summary", result), "capital_change", None) is not None
            )
            try:
                stable = _external_key(session) == snapshot[0]
            except (OSError, ValueError):
                stable = False
            encoded = (
                pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
                if stable and complete
                else None
            )
        # Publish only after the snapshot's mutation and cleanup guards succeed.
        # A reader that accidentally dirties ORM state must never seed a hit.
        if encoded is not None and len(encoded) <= MAX_CACHE_BYTES:
            with _lock:
                previous = _entries.pop(key, b"")
                _size += len(encoded) - len(previous)
                _entries[key] = encoded
                while len(_entries) > MAX_ENTRIES or _size > MAX_CACHE_BYTES:
                    _, removed = _entries.popitem(last=False)
                    _size -= len(removed)
        return result

    wrapped.__signature__ = signature
    return wrapped
