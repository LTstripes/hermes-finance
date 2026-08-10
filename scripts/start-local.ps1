[CmdletBinding()]
param(
    [switch]$ExitAfterReady
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$frontendDist = Join-Path $frontendDir "dist"
$backendProcess = $null
$exitCode = 0

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

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    if ($null -eq (Get-Command "Get-NetTCPConnection" -ErrorAction SilentlyContinue)) {
        return
    }

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($null -ne $listener) {
        throw "Port $Port is already in use. Stop the existing process before starting Hermes Finance."
    }
}

function Assert-ProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $Process.Refresh()
    if ($Process.HasExited) {
        throw "$Name stopped unexpectedly with exit code $($Process.ExitCode)."
    }
}

function Invoke-FrontendBuild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Npm,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    Write-Host "Building frontend production bundle..." -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & $Npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend production build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

function Wait-ForProductionStack {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        Assert-ProcessRunning -Process $Backend -Name "Backend"

        try {
            $health = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/api/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            $months = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/api/months" `
                -UseBasicParsing `
                -TimeoutSec 2
            $frontend = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/" `
                -UseBasicParsing `
                -TimeoutSec 2
            if (
                $health.StatusCode -eq 200 -and
                $months.StatusCode -eq 200 -and
                $frontend.StatusCode -eq 200 -and
                $frontend.Content -match "Hermes Finance"
            ) {
                return
            }
        }
        catch {
            # The backend may still be starting; the process check above catches early exits.
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Production stack did not become ready within 45 seconds."
}

function Stop-ProcessTree {
    param(
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($null -eq $Process) {
        return
    }

    $Process.Refresh()
    if ($Process.HasExited) {
        return
    }

    Write-Host "Stopping $Name..." -ForegroundColor DarkGray
    $taskKill = Start-Process `
        -FilePath (Join-Path $env:SystemRoot "System32\taskkill.exe") `
        -ArgumentList @("/PID", $Process.Id, "/T", "/F") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($taskKill.ExitCode -ne 0) {
        throw "Failed to stop $Name process tree (PID $($Process.Id))."
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

    Invoke-FrontendBuild -Npm $npm -WorkingDirectory $frontendDir
    if (-not (Test-Path (Join-Path $frontendDist "index.html") -PathType Leaf)) {
        throw "Frontend build completed without '$frontendDist\index.html'."
    }

    Assert-PortAvailable -Port 8000

    $savedEnvironment = @{}
    foreach ($name in @(
        "HERMES_FINANCE_HOST",
        "HERMES_FINANCE_PORT",
        "HERMES_FINANCE_RELOAD",
        "HERMES_FINANCE_FRONTEND_DIST",
        "PYTHONPATH"
    )) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        $env:HERMES_FINANCE_HOST = "127.0.0.1"
        $env:HERMES_FINANCE_PORT = "8000"
        $env:HERMES_FINANCE_RELOAD = "false"
        $env:HERMES_FINANCE_FRONTEND_DIST = $frontendDist
        $env:PYTHONPATH = ""

        Write-Host "Starting Hermes Finance production backend..." -ForegroundColor Cyan
        $backendProcess = Start-Process `
            -FilePath $uv `
            -ArgumentList @("run", "hermes-finance-api") `
            -WorkingDirectory $backendDir `
            -NoNewWindow `
            -PassThru
    }
    finally {
        foreach ($name in $savedEnvironment.Keys) {
            $value = $savedEnvironment[$name]
            if ($null -eq $value) {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:$name" $value
            }
        }
    }

    Wait-ForProductionStack -Backend $backendProcess
    Write-Host "Hermes Finance is ready: http://127.0.0.1:8000" -ForegroundColor Green
    if ($ExitAfterReady) {
        Write-Host "Production readiness smoke test passed." -ForegroundColor Green
    }
    else {
        Write-Host "Press Ctrl+C to stop Hermes Finance." -ForegroundColor DarkGray
        while ($true) {
            Assert-ProcessRunning -Process $backendProcess -Name "Backend"
            Start-Sleep -Seconds 1
        }
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    Stop-ProcessTree -Process $backendProcess -Name "backend"
}

exit $exitCode
