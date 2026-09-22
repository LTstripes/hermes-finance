from __future__ import annotations

import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from hermes_finance.services import recovery_process
from hermes_finance.services.recovery_process import ProcessTreeError, run_owned_process
from hermes_finance.services.recovery_rehearsal import (
    CheckoutProof,
    RecoveryRehearsalError,
    _run_runtime_script,
)

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
child_arguments = [sys.executable, "-c", sys.argv[3], str(marker)]
if mode == "exit-inherit":
    subprocess.Popen(child_arguments, stdin=subprocess.DEVNULL)
else:
    subprocess.Popen(
        child_arguments,
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


_FOREIGN_HEALTHY_SERVER = """
import http.server
import os
import sys
import time
from pathlib import Path

token, database, checkout, start_marker, ready_marker = sys.argv[1:]

deadline = time.monotonic() + 15
while not Path(start_marker).exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if not Path(start_marker).exists():
    raise SystemExit(98)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"[]" if self.path.startswith("/api/") else b"Hermes Finance"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Hermes-Recovery-Token", token)
        self.send_header("X-Hermes-Recovery-Database-Identity", database)
        self.send_header("X-Hermes-Recovery-Checkout-SHA", checkout)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return

server = http.server.ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
Path(ready_marker).write_text(str(os.getpid()), encoding="utf-8")
server.serve_forever()
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


def test_wrapper_exit_with_pipe_inheriting_descendant_still_cleans_owned_tree(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "wrapper-exit-child.txt"

    completed = run_owned_process(
        _command(marker, "exit-inherit"),
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

        def wait(self, timeout: int | float | None = None) -> int:
            return self.returncode

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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows competing-runtime contract")
def test_real_competing_runtime_cannot_satisfy_recovery_readiness_or_be_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    with socket.socket() as availability:
        try:
            availability.bind(("127.0.0.1", 8000))
        except OSError:
            pytest.skip("port 8000 is unavailable for the competing-runtime regression")

    token = "a" * 64
    database_identity = "b" * 64
    checkout_sha = "c" * 40
    foreign_start = tmp_path / "foreign-runtime-start.txt"
    foreign_marker = tmp_path / "foreign-runtime.txt"
    foreign = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FOREIGN_HEALTHY_SERVER,
            token,
            database_identity,
            checkout_sha,
            str(foreign_start),
            str(foreign_marker),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    checkout = tmp_path / "synthetic-recovery-checkout"
    scripts = checkout / "scripts"
    backend = checkout / "backend"
    frontend = checkout / "frontend"
    scripts.mkdir(parents=True)
    backend.mkdir()
    frontend.mkdir()
    for name in (
        "start-local.ps1",
        "recovery-runtime-boundary.ps1",
        "recovery-runtime-safety.ps1",
    ):
        shutil.copy2(REPOSITORY_ROOT / "scripts" / name, scripts)
    (backend / "pyproject.toml").write_text("synthetic\n", encoding="utf-8")
    (frontend / "package.json").write_text("{}\n", encoding="utf-8")
    owned_script = tmp_path / "owned-validation-child.py"
    owned_script.write_text(_CHILD_CODE, encoding="utf-8")
    owned_marker = tmp_path / "owned-validation-child.txt"
    (scripts / "prepare-runtime.ps1").write_text(
        "param([string]$Checkout, [switch]$Validate)\n"
        "if (-not $Validate) { exit 8 }\n"
        "$null = Start-Process -FilePath $env:HERMES_TEST_PYTHON "
        "-ArgumentList @($env:HERMES_TEST_OWNED_SCRIPT, $env:HERMES_TEST_OWNED_MARKER) "
        "-WindowStyle Hidden -PassThru\n"
        "Write-Output 'runtime=prepared'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    backend_invoked = tmp_path / "backend-invoked.txt"
    fake_backend = tmp_path / "owned-fake-backend.py"
    fake_backend.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    (fake_bin / "uv.cmd").write_text(
        "@echo off\n"
        '> "%HERMES_TEST_BACKEND_INVOKED%" echo invoked\n'
        '> "%HERMES_TEST_FOREIGN_START%" echo start\n'
        '"%HERMES_TEST_PYTHON%" "%HERMES_TEST_FAKE_BACKEND%"\n'
        "exit /b 9\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ["PATH"])
    proof = CheckoutProof(
        checkout=checkout,
        selected_sha=checkout_sha,
        repository_key="synthetic",
        git_directory=checkout / ".git",
        common_directory=checkout / ".git",
    )
    try:
        with pytest.raises(RecoveryRehearsalError) as captured:
            _run_runtime_script(
                proof,
                script_name="start-local.ps1",
                arguments=["-ExitAfterReady", "-RecoveryReadiness"],
                stage="runtime-start",
                environment_overrides={
                    "HERMES_FINANCE_RECOVERY_READINESS_TOKEN": token,
                    "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY": database_identity,
                    "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA": checkout_sha,
                    "HERMES_TEST_PYTHON": sys.executable,
                    "HERMES_TEST_OWNED_SCRIPT": str(owned_script),
                    "HERMES_TEST_OWNED_MARKER": str(owned_marker),
                    "HERMES_TEST_BACKEND_INVOKED": str(backend_invoked),
                    "HERMES_TEST_FOREIGN_START": str(foreign_start),
                    "HERMES_TEST_FAKE_BACKEND": str(fake_backend),
                },
                timeout=30,
            )

        assert captured.value.stage == "runtime-start"
        owned_id, owned_port = _marker_identity(owned_marker)
        _wait_until_gone(owned_id)
        _assert_listener_gone(owned_port)
        assert backend_invoked.exists()
        deadline = time.monotonic() + 10
        while not foreign_marker.exists() and time.monotonic() < deadline:
            if foreign.poll() is not None:
                pytest.fail("synthetic competing runtime exited before listening")
            time.sleep(0.05)
        assert foreign_marker.exists()
        assert foreign.poll() is None
        urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2).close()
    finally:
        foreign.terminate()
        foreign.wait(timeout=10)
