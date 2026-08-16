"""R04-08: Windows PowerShell 5.1 must keep a spaced launcher path intact."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "windows-powershell-file.ps1"
WINDOWS_POWERSHELL = Path(
    os.environ.get("SystemRoot", r"C:\Windows"),
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe",
)


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_windows_powershell_file(script_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(WINDOWS_POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _write_probe(directory: Path, output_path: Path) -> Path:
    probe = directory / "start-local.ps1"
    probe.write_text(
        (
            "Set-StrictMode -Version 2.0\n"
            f"Set-Content -LiteralPath {_ps_single_quote(str(output_path))} "
            "-Value $PSCommandPath\n"
            "exit 0\n"
        ),
        encoding="utf-8",
        newline="\n",
    )
    return probe


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 argument splitting")
def test_unquoted_start_process_argumentlist_splits_path_with_spaces(tmp_path: Path) -> None:
    """Negative control: the 5.1 Start-Process array join is the real defect."""

    if not WINDOWS_POWERSHELL.is_file():
        pytest.skip("Windows PowerShell 5.1 is not installed")

    spaced = tmp_path / "Directory With Spaces"
    spaced.mkdir()
    observed = tmp_path / "unquoted-observed.txt"
    probe = _write_probe(spaced, observed)
    assert " " in str(probe)

    driver = tmp_path / "unquoted-driver.ps1"
    driver.write_text(
        (
            "Set-StrictMode -Version 2.0\n"
            "$ErrorActionPreference = 'Stop'\n"
            f"$powershell = {_ps_single_quote(str(WINDOWS_POWERSHELL))}\n"
            f"$probe = {_ps_single_quote(str(probe))}\n"
            "$process = Start-Process -FilePath $powershell -ArgumentList @(\n"
            "    '-NoProfile',\n"
            "    '-ExecutionPolicy',\n"
            "    'Bypass',\n"
            "    '-File',\n"
            "    $probe\n"
            ") -PassThru -WindowStyle Hidden\n"
            "if (-not $process.WaitForExit(15000)) {\n"
            "    $process.Kill()\n"
            "    throw 'unquoted Start-Process timed out'\n"
            "}\n"
            "exit $process.ExitCode\n"
        ),
        encoding="utf-8",
        newline="\n",
    )

    completed = _run_windows_powershell_file(driver)
    assert not observed.is_file(), completed.stdout + completed.stderr
    assert completed.returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 argument splitting")
def test_canonical_launcher_path_with_spaces_reaches_powershell_file(tmp_path: Path) -> None:
    if not WINDOWS_POWERSHELL.is_file():
        pytest.skip("Windows PowerShell 5.1 is not installed")
    assert HELPER.is_file()

    spaced = tmp_path / "Directory With Spaces"
    spaced.mkdir()
    observed = tmp_path / "quoted-observed.txt"
    probe = _write_probe(spaced, observed)
    assert " " in str(probe)

    driver = tmp_path / "quoted-driver.ps1"
    driver.write_text(
        (
            "Set-StrictMode -Version 2.0\n"
            "$ErrorActionPreference = 'Stop'\n"
            f". {_ps_single_quote(str(HELPER))}\n"
            f"$probe = {_ps_single_quote(str(probe))}\n"
            f"$working = {_ps_single_quote(str(spaced))}\n"
            "$process = Start-WindowsPowerShellFile -FilePath $probe "
            "-WorkingDirectory $working\n"
            "if (-not $process.WaitForExit(15000)) {\n"
            "    $process.Kill()\n"
            "    throw 'quoted launcher start timed out'\n"
            "}\n"
            "if ($process.ExitCode -ne 0) {\n"
            "    throw 'quoted launcher exited with a non-zero status'\n"
            "}\n"
        ),
        encoding="utf-8",
        newline="\n",
    )

    completed = _run_windows_powershell_file(driver)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert observed.is_file(), completed.stdout + completed.stderr
    reported = Path(observed.read_text(encoding="utf-8").strip())
    assert Path(os.path.normcase(reported)) == Path(os.path.normcase(probe.resolve()))
    assert "Directory With Spaces" in str(reported)
    assert reported.name == "start-local.ps1"
