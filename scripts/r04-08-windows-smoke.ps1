[CmdletBinding()]
param()

# R04-08 canonical Windows production smoke.
# Isolated temp DB, no token read, no live T-Invest probe.
# Proves the live production listener is exactly 127.0.0.1:8000.

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$launcher = Join-Path $repoRoot "scripts\start-local.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("hermes-r04-08-" + [guid]::NewGuid().ToString("N"))
$databasePath = Join-Path $tempRoot "finance.db"
$launcherProcess = $null
$listenPort = 8000

if (-not (Test-Path $launcher -PathType Leaf)) {
    throw "Canonical launcher not found at '$launcher'."
}

function Get-TcpListenAddresses {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $endpoints = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    $addresses = @()
    foreach ($endpoint in $endpoints) {
        if ($endpoint.Port -eq $Port) {
            $addresses += $endpoint.Address.ToString()
        }
    }
    return $addresses
}

function Assert-ExactLoopbackListener {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $addresses = @(Get-TcpListenAddresses -Port $Port)
    if ($addresses.Count -eq 0) {
        throw "Production launcher is ready but port $Port has no TCP listener."
    }
    $unexpected = @($addresses | Where-Object { $_ -ne "127.0.0.1" })
    if ($unexpected.Count -gt 0) {
        throw (
            "Port $Port is listening on unexpected address(es): $($unexpected -join ', '). " +
            "Expected only 127.0.0.1."
        )
    }
    if ($addresses -notcontains "127.0.0.1") {
        throw "Port $Port is not bound to 127.0.0.1."
    }
}

function Assert-NoListener {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = @(Get-TcpListenAddresses -Port $Port)
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Port $Port still listening after shutdown: $($remaining -join ', ')."
}

function Wait-ForProductionStack {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(180)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "Canonical launcher exited before becoming ready (exit code $($Process.ExitCode))."
        }

        try {
            $health = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$listenPort/api/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            $months = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$listenPort/api/months" `
                -UseBasicParsing `
                -TimeoutSec 2
            $frontend = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$listenPort/" `
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
            # Frontend build or backend may still be starting.
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Canonical production launcher did not become ready within 180 seconds."
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
        -ArgumentList @("/PID", "$($Process.Id)", "/T", "/F") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($taskKill.ExitCode -ne 0) {
        throw "Failed to stop $Name process tree (PID $($Process.Id))."
    }
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
    $launcherProcess = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $launcher
        ) `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -PassThru

    Wait-ForProductionStack -Process $launcherProcess
    if (-not (Test-Path $databasePath -PathType Leaf)) {
        throw "Canonical launcher did not create the isolated SQLite database."
    }

    Write-Host "R04-08 Windows smoke: production stack is live; inspecting TCP listener." -ForegroundColor Cyan
    Assert-ExactLoopbackListener -Port $listenPort
    Write-Host "R04-08 Windows smoke: port $listenPort is bound only to 127.0.0.1." -ForegroundColor Green
}
finally {
    Stop-ProcessTree -Process $launcherProcess -Name "canonical launcher"
    if ($null -eq $savedDatabase) {
        Remove-Item Env:HERMES_FINANCE_DATABASE_PATH -ErrorAction SilentlyContinue
    }
    else {
        $env:HERMES_FINANCE_DATABASE_PATH = $savedDatabase
    }
}

try {
    Assert-NoListener -Port $listenPort
    Write-Host "R04-08 Windows smoke: listener on port $listenPort is gone after shutdown." -ForegroundColor Green
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
