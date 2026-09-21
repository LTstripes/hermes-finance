from __future__ import annotations

import ctypes
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

import pytest

from hermes_finance.services import recovery_process
from hermes_finance.services.recovery_process import ProcessTreeError, run_owned_process

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

_CHILD_CODE = """
import os
import socket
import sys
import time
from pathlib import Path

listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(1)
Path(sys.argv[1]).write_text(
    f"{os.getpid()}:{listener.getsockname()[1]}",
    encoding="utf-8",
)
time.sleep(60)
"""


_WRAPPER_CODE = """
import subprocess
import sys
import time
from pathlib import Path

if not sys.stdin.readline().strip():
    raise SystemExit(97)
marker = Path(sys.argv[1])
mode = sys.argv[2]
subprocess.Popen(
    [sys.executable, "-c", sys.argv[3], str(marker)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
deadline = time.monotonic() + 5
while not marker.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if not marker.exists():
    raise SystemExit(98)
if mode == "timeout":
    time.sleep(60)
"""


def _command(marker: Path, mode: str) -> list[str]:
    return [sys.executable, "-c", _WRAPPER_CODE, str(marker), mode, _CHILD_CODE]


def _process_exists(process_id: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_gone(process_id: int) -> None:
    deadline = time.monotonic() + 5
    while _process_exists(process_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _process_exists(process_id)


def _marker_identity(marker: Path) -> tuple[int, int]:
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    process_id, port = marker.read_text(encoding="utf-8").split(":", 1)
    return int(process_id), int(port)


def _assert_listener_gone(port: int) -> None:
    with socket.socket() as probe:
        probe.settimeout(0.25)
        assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_timeout_after_child_start_cleans_owned_descendant_and_listener(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "timeout-child.txt"

    with pytest.raises(ProcessTreeError) as captured:
        run_owned_process(
            _command(marker, "timeout"),
            cwd=tmp_path,
            environment=os.environ.copy(),
            ownership_token="timeout-token",
            timeout=1.5,
        )

    assert captured.value.reason == "timeout"
    child_id, port = _marker_identity(marker)
    _wait_until_gone(child_id)
    _assert_listener_gone(port)


def test_wrapper_exit_with_live_descendant_still_cleans_owned_tree(tmp_path: Path) -> None:
    marker = tmp_path / "wrapper-exit-child.txt"

    completed = run_owned_process(
        _command(marker, "exit"),
        cwd=tmp_path,
        environment=os.environ.copy(),
        ownership_token="wrapper-exit-token",
        timeout=10,
    )

    assert completed.returncode == 0
    child_id, port = _marker_identity(marker)
    _wait_until_gone(child_id)
    _assert_listener_gone(port)


def test_cleanup_failure_is_reported_instead_of_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeProcess:
        returncode = 0

        def communicate(
            self, input: str | None = None, timeout: int | float | None = None
        ) -> tuple[str, str]:
            return "", ""

    class FailingOwner:
        def cleanup(self) -> None:
            raise ProcessTreeError("cleanup-failed")

    monkeypatch.setattr(
        recovery_process,
        "_spawn_owned_process",
        lambda *_args, **_kwargs: (FakeProcess(), FailingOwner()),
    )

    with pytest.raises(ProcessTreeError) as captured:
        run_owned_process(
            ["synthetic"],
            cwd=tmp_path,
            environment={},
            ownership_token="token",
            timeout=1,
        )

    assert captured.value.reason == "cleanup-failed"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell boundary contract")
def test_powershell_boundary_preserves_string_argument_vector(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    marker = tmp_path / "argument-vector.txt"
    child = tmp_path / "argument-probe.ps1"
    child.write_text(
        "param([Parameter(Mandatory = $true)][string]$Checkout, [switch]$Prepare)\n"
        "if (-not $Prepare) { exit 8 }\n"
        "[IO.File]::WriteAllText($Checkout, 'preserved')\n"
        "exit 0\n",
        encoding="utf-8",
    )
    token = "argument-vector-token"
    completed = run_owned_process(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPOSITORY_ROOT / "scripts" / "recovery-runtime-boundary.ps1"),
            "-Script",
            str(child),
            "-ArgumentsJson",
            json.dumps(["-Checkout", str(marker), "-Prepare"], separators=(",", ":")),
            "-OwnershipToken",
            token,
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
        ownership_token=token,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8") == "preserved"
