[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Missing dependency '$Name'. $InstallHint"
    }

    return $command.Source
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

try {
    $uv = Get-RequiredCommand -Name "uv" -InstallHint "Install uv from https://docs.astral.sh/uv/."
    $npm = Get-RequiredCommand -Name "npm.cmd" -InstallHint "Install Node.js 22.22 or newer from https://nodejs.org/."

    if (-not (Test-Path (Join-Path $backendDir "pyproject.toml") -PathType Leaf)) {
        throw "Backend project not found at '$backendDir'. Run this script from the Hermes Finance repository."
    }
    if (-not (Test-Path (Join-Path $frontendDir "package.json") -PathType Leaf)) {
        throw "Frontend project not found at '$frontendDir'. Run this script from the Hermes Finance repository."
    }
    if (-not (Test-Path (Join-Path $frontendDir "node_modules") -PathType Container)) {
        throw "Frontend dependencies are missing. Run 'cd frontend' and then 'npm ci'."
    }

    Push-Location $backendDir
    try {
        Invoke-NativeStep -Label "Checking backend formatting" -Action {
            & $uv run --locked ruff format --check .
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $frontendDir
    try {
        Invoke-NativeStep -Label "Checking frontend formatting" -Action {
            & $npm run format-check
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Backend and frontend format checks passed." -ForegroundColor Green
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
