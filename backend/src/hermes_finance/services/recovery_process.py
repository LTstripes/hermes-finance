"""Owned process-tree execution for bounded recovery runtime operations."""

from __future__ import annotations

import ctypes
import hashlib
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProcessTreeError(RuntimeError):
    """An owned command could not be launched, bounded, or fully cleaned up."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def file_identity_token(path: Path) -> str:
    """Return a non-path-bearing identity token for one regular, non-linked file."""

    inspected = path.lstat()
    device = int(getattr(inspected, "st_dev", 0))
    inode = int(getattr(inspected, "st_ino", 0))
    if (
        path.is_symlink()
        or bool(getattr(inspected, "st_file_attributes", 0) & 0x400)
        or not stat.S_ISREG(inspected.st_mode)
        or inspected.st_nlink != 1
        or (device == 0 and inode == 0)
    ):
        raise OSError("runtime database identity is unavailable")
    return hashlib.sha256(f"{device}:{inode}".encode("ascii")).hexdigest()


class _TreeOwner(Protocol):
    def cleanup(self) -> None: ...


if sys.platform == "win32":

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operation_count", ctypes.c_ulonglong),
            ("write_operation_count", ctypes.c_ulonglong),
            ("other_operation_count", ctypes.c_ulonglong),
            ("read_transfer_count", ctypes.c_ulonglong),
            ("write_transfer_count", ctypes.c_ulonglong),
            ("other_transfer_count", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_longlong),
            ("per_job_user_time_limit", ctypes.c_longlong),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", _BasicLimitInformation),
            ("io_info", _IoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]

    class _BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("total_user_time", ctypes.c_longlong),
            ("total_kernel_time", ctypes.c_longlong),
            ("this_period_total_user_time", ctypes.c_longlong),
            ("this_period_total_kernel_time", ctypes.c_longlong),
            ("total_page_fault_count", wintypes.DWORD),
            ("total_processes", wintypes.DWORD),
            ("active_processes", wintypes.DWORD),
            ("total_terminated_processes", wintypes.DWORD),
        ]

    class _AssociateCompletionPort(ctypes.Structure):
        _fields_ = [("key", ctypes.c_void_p), ("port", wintypes.HANDLE)]


def _windows_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CloseHandle": ((wintypes.HANDLE,), wintypes.BOOL),
        "CreateIoCompletionPort": (
            (wintypes.HANDLE, wintypes.HANDLE, ctypes.c_size_t, wintypes.DWORD),
            wintypes.HANDLE,
        ),
        "GetQueuedCompletionStatus": (
            (
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_void_p),
                wintypes.DWORD,
            ),
            wintypes.BOOL,
        ),
        "OpenProcess": ((wintypes.DWORD, wintypes.BOOL, wintypes.DWORD), wintypes.HANDLE),
        "IsProcessInJob": (
            (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)),
            wintypes.BOOL,
        ),
        "WaitForSingleObject": ((wintypes.HANDLE, wintypes.DWORD), wintypes.DWORD),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel32, name)
        function.argtypes = arguments
        function.restype = result
    return kernel32


@dataclass(slots=True)
class _WindowsJob:
    handle: int
    completion_port: int = 0
    closed: bool = False

    @classmethod
    def create(cls) -> _WindowsJob:
        kernel32 = _windows_kernel32()
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        create_job.restype = wintypes.HANDLE
        handle = create_job(None, None)
        if not handle:
            raise ProcessTreeError("ownership-unavailable")

        information = _ExtendedLimitInformation()
        information.basic_limit_information.limit_flags = 0x00002000
        set_information = kernel32.SetInformationJobObject
        set_information.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        set_information.restype = wintypes.BOOL
        if not set_information(
            handle,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            kernel32.CloseHandle(handle)
            raise ProcessTreeError("ownership-unavailable")
        port = kernel32.CreateIoCompletionPort(wintypes.HANDLE(-1), None, 0, 1)
        if not port:
            kernel32.CloseHandle(handle)
            raise ProcessTreeError("ownership-unavailable")
        association = _AssociateCompletionPort(1, port)
        if not set_information(handle, 7, ctypes.byref(association), ctypes.sizeof(association)):
            kernel32.CloseHandle(port)
            kernel32.CloseHandle(handle)
            raise ProcessTreeError("ownership-unavailable")
        return cls(handle=int(handle), completion_port=int(port))

    def assign(self, process: subprocess.Popen[str]) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        assign = kernel32.AssignProcessToJobObject
        assign.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        assign.restype = wintypes.BOOL
        process_handle = int(getattr(process, "_handle"))
        if not assign(self.handle, process_handle):
            raise ProcessTreeError("ownership-unavailable")

    def _accounting(self) -> _BasicAccountingInformation:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        query = kernel32.QueryInformationJobObject
        query.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        query.restype = wintypes.BOOL
        information = _BasicAccountingInformation()
        returned = wintypes.DWORD()
        if not query(
            self.handle,
            1,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise ProcessTreeError("cleanup-unverified")
        return information

    def _active_processes(self) -> int:
        return int(self._accounting().active_processes)

    def _wait_for_disposition(self, deadline: float) -> None:
        # ActiveProcesses and the job PID list can become empty *before* a
        # terminating process is signaled and releases its listener. The port
        # was associated before assignment: NEW_PROCESS messages also retain
        # identities of children that have already left those active lists.
        # Notifications are not guaranteed, so reconcile against the lifetime
        # process count and fail closed if evidence is missing by the deadline.
        kernel32 = _windows_kernel32()
        expected = int(self._accounting().total_processes)
        observed = 0
        while observed < expected:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTreeError("cleanup-unverified")
            message = wintypes.DWORD()
            key = ctypes.c_size_t()
            process_id = ctypes.c_void_p()
            if not kernel32.GetQueuedCompletionStatus(
                self.completion_port,
                ctypes.byref(message),
                ctypes.byref(key),
                ctypes.byref(process_id),
                max(1, int(remaining * 1000)),
            ):
                raise ProcessTreeError("cleanup-unverified")
            if key.value != 1:
                raise ProcessTreeError("cleanup-unverified")
            if message.value != 6:  # JOB_OBJECT_MSG_NEW_PROCESS
                continue
            observed += 1
            if not process_id.value:
                raise ProcessTreeError("cleanup-unverified")
            handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, process_id.value)
            if not handle:
                if ctypes.get_last_error() == 87:  # PID no longer exists.
                    continue
                raise ProcessTreeError("cleanup-unverified")
            try:
                belongs = wintypes.BOOL()
                if not kernel32.IsProcessInJob(handle, self.handle, ctypes.byref(belongs)):
                    raise ProcessTreeError("cleanup-unverified")
                if not belongs.value:
                    # Recycled PID: the original process object is already gone.
                    # Never wait on or terminate an unrelated replacement.
                    continue
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                if kernel32.WaitForSingleObject(handle, remaining_ms) != 0:
                    raise ProcessTreeError("cleanup-unverified")
            finally:
                kernel32.CloseHandle(handle)
        final = self._accounting()
        if final.active_processes != 0 or final.total_processes != observed:
            raise ProcessTreeError("cleanup-unverified")

    def cleanup(self) -> None:
        if self.closed:
            return
        kernel32 = _windows_kernel32()
        terminate = kernel32.TerminateJobObject
        terminate.argtypes = (wintypes.HANDLE, wintypes.UINT)
        terminate.restype = wintypes.BOOL
        deadline = time.monotonic() + 5.0
        try:
            if not terminate(self.handle, 1):
                raise ProcessTreeError("cleanup-failed")
            while self._active_processes() != 0:
                if time.monotonic() >= deadline:
                    raise ProcessTreeError("cleanup-unverified")
                time.sleep(0.05)
            self._wait_for_disposition(deadline)
        finally:
            kernel32.CloseHandle(self.handle)
            kernel32.CloseHandle(self.completion_port)
            self.closed = True

    def close_unassigned(self) -> None:
        if self.closed:
            return
        kernel32 = _windows_kernel32()
        kernel32.CloseHandle(self.handle)
        kernel32.CloseHandle(self.completion_port)
        self.closed = True


@dataclass(slots=True)
class _PosixProcessGroup:
    process_group_id: int
    process: subprocess.Popen[str]

    def _exists(self) -> bool:
        try:
            os.killpg(self.process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError as error:
            raise ProcessTreeError("cleanup-unverified") from error
        return True

    def cleanup(self) -> None:
        if not self._exists():
            return
        try:
            os.killpg(self.process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1.0
        while self._exists() and time.monotonic() < deadline:
            self.process.poll()
            time.sleep(0.05)
        if self._exists():
            try:
                os.killpg(self.process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                return
            deadline = time.monotonic() + 4.0
            while self._exists() and time.monotonic() < deadline:
                self.process.poll()
                time.sleep(0.05)
        if self._exists():
            raise ProcessTreeError("cleanup-unverified")


def _spawn_owned_process(
    command: list[str], *, cwd: Path, environment: dict[str, str]
) -> tuple[subprocess.Popen[str], _TreeOwner]:
    popen_kwargs: dict[str, object] = {
        "cwd": cwd,
        "env": environment,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        owner = _WindowsJob.create()
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as error:
            owner.close_unassigned()
            raise ProcessTreeError("launch-failed") from error
        try:
            owner.assign(process)
        except ProcessTreeError:
            try:
                process.kill()
                process.communicate(timeout=5)
            finally:
                owner.close_unassigned()
            raise
        return process, owner

    popen_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **popen_kwargs)
    except OSError as error:
        raise ProcessTreeError("launch-failed") from error
    return process, _PosixProcessGroup(process.pid, process)


def run_owned_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    ownership_token: str,
    timeout: int | float,
) -> subprocess.CompletedProcess[str]:
    """Run a gated wrapper and prove its entire owned process tree is gone."""

    process, owner = _spawn_owned_process(command, cwd=cwd, environment=environment)
    communication_result: tuple[str, str] | None = None
    communication_error: BaseException | None = None

    def communicate() -> None:
        nonlocal communication_result, communication_error
        try:
            communication_result = process.communicate(input=ownership_token + "\n")
        except BaseException as error:
            communication_error = error

    communicator = threading.Thread(target=communicate, daemon=True)
    communicator.start()
    pending_error: BaseException | None = None
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pending_error = ProcessTreeError("timeout")
    except BaseException as error:
        pending_error = error

    cleanup_error: ProcessTreeError | None = None
    try:
        owner.cleanup()
    except ProcessTreeError as error:
        cleanup_error = error

    communicator.join(timeout=5)
    if cleanup_error is not None:
        pending_error = cleanup_error
    elif communicator.is_alive():
        pending_error = ProcessTreeError("cleanup-unverified")
    elif communication_error is not None and pending_error is None:
        pending_error = communication_error

    if pending_error is not None:
        if isinstance(pending_error, ProcessTreeError):
            raise pending_error
        raise pending_error
    if communication_result is None:
        raise ProcessTreeError("cleanup-unverified")
    stdout, stderr = communication_result
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
