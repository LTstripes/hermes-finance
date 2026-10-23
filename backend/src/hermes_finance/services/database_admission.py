"""Common pre-writer admission for stock Start and offline forward recovery.

The kernel lock is volatile. The adjacent fence is durable and is never cleared
by Start. A recovery command owns the same lock; no environment bypass exists.
Existing SQLite connections additionally prevent Windows deny-write custody.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class AdmissionError(RuntimeError):
    """A privacy-safe pre-writer refusal."""


_registry_lock = threading.Condition(threading.RLock())


@dataclass
class _Owner:
    recovery: bool
    borrowers: int = 0
    closing: bool = False


_owners: dict[str, _Owner] = {}


def fence_path(database: Path) -> Path:
    return database.with_name(database.name + ".hermes-recovery.json")


def _key(database: Path) -> str:
    return hashlib.sha256(
        os.path.normcase(str(database.expanduser().resolve())).encode()
    ).hexdigest()


def assert_unfenced(database: Path) -> None:
    # lexists rejects dangling links and malformed/empty fences too.
    if os.path.lexists(fence_path(database)):
        raise AdmissionError("database_recovery_fenced")


@contextmanager
def database_admission(database: Path, *, recovery: bool = False):
    """Fail rather than wait; runtime nesting is allowed, recovery nesting is not.

    The outer context owns the native mutex on its calling thread. Runtime SQL
    connection admission may nest on worker threads while the stock CLI owns it.
    The CLI does not exit this outer context until server/engine cleanup finishes.
    """
    database = Path(database).expanduser().resolve()
    key = _key(database)
    nested = False
    handle = None
    stream = None
    kernel = None
    with _registry_lock:
        if key in _owners:
            if recovery or _owners[key].recovery or _owners[key].closing:
                raise AdmissionError("database_admission_busy")
            nested = True
            _owners[key].borrowers += 1
        elif sys.platform == "win32":
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            kernel.ReleaseMutex.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.CreateMutexW(None, False, "Global\\HermesDatabase-" + key)
            if not handle:
                raise AdmissionError("database_admission_unavailable")
            # WAIT_ABANDONED grants ownership, but never waives a durable fence.
            if kernel.WaitForSingleObject(handle, 0) not in (0, 0x80):
                kernel.CloseHandle(handle)
                raise AdmissionError("database_admission_busy")
        else:
            import fcntl

            stream = open(Path(tempfile.gettempdir()) / ("hermes-admission-" + key), "a+b")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                stream.close()
                raise AdmissionError("database_admission_busy") from None
        if not nested:
            _owners[key] = _Owner(recovery)
    try:
        if not recovery:
            assert_unfenced(database)
        yield
    finally:
        if nested:
            with _registry_lock:
                _owners[key].borrowers -= 1
                _registry_lock.notify_all()
        else:
            with _registry_lock:
                _owners[key].closing = True
                while _owners[key].borrowers:
                    _registry_lock.wait()
                _owners.pop(key, None)
                if handle is not None:
                    kernel.ReleaseMutex(handle)
                    kernel.CloseHandle(handle)
                if stream is not None:
                    stream.close()
