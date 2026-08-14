[CmdletBinding()]
param()

# R04-08 canonical Windows production smoke.
# Isolated temp DB, no token read, no live T-Invest probe.

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$launcher = Join-Path $repoRoot "scripts\start-local.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("hermes-r04-08-" + [guid]::NewGuid().ToString("N"))
$databasePath = Join-Path $tempRoot "finance.db"

if (-not (Test-Path $launcher -PathType Leaf)) {
    throw "Canonical launcher not found at '$launcher'."
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null

$savedDatabase = [Environment]::GetEnvironmentVariable(
    "HERMES_FINANCE_DATABASE_PATH",
    "Process"
)

try {
    # Unset without reading. The smoke must not print or copy the token value.
    Remove-Item Env:HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN -ErrorAction SilentlyContinue
    $env:HERMES_FINANCE_DATABASE_PATH = $databasePath

    Write-Host "R04-08 Windows smoke: starting canonical launcher with isolated DB." -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcher -ExitAfterReady
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical launcher failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path $databasePath -PathType Leaf)) {
        throw "Canonical launcher did not create the isolated SQLite database."
    }

    if ($null -ne (Get-Command "Get-NetTCPConnection" -ErrorAction SilentlyContinue)) {
        $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
        if ($null -ne $listener) {
            throw "Canonical launcher left port 8000 listening after -ExitAfterReady."
        }
    }

    Write-Host "R04-08 Windows smoke: launcher started, bound via 127.0.0.1:8000, and shut down cleanly." -ForegroundColor Green
}
finally {
    if ($null -eq $savedDatabase) {
        Remove-Item Env:HERMES_FINANCE_DATABASE_PATH -ErrorAction SilentlyContinue
    }
    else {
        $env:HERMES_FINANCE_DATABASE_PATH = $savedDatabase
    }
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
