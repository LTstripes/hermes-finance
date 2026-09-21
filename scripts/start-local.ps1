[CmdletBinding()]
param(
    [switch]$ExitAfterReady,
    [switch]$RecoveryReadiness
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

function Invoke-PreparedRuntimeValidation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PowerShell,
        [Parameter(Mandatory = $true)]
        [string]$Checkout
    )

    $preparedStateScript = Join-Path $Checkout "scripts\prepare-runtime.ps1"
    if (-not (Test-Path -LiteralPath $preparedStateScript -PathType Leaf)) {
        throw "Prepared runtime validation is unavailable. Run the explicit Prepare command from a complete Hermes Finance checkout."
    }

    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $PowerShell `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $preparedStateScript `
            -Checkout $Checkout `
            -Validate 2>&1 | Out-String
        $validationExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($validationExitCode -ne 0) {
        $detail = $output.Trim()
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = "Prepared runtime validation failed without a diagnostic."
        }
        throw $detail
    }
}

function Wait-ForProductionStack {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend,
        [Parameter(Mandatory = $true)]
        [bool]$RequireRecoverySurfaces
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
            $baseReady = (
                $health.StatusCode -eq 200 -and
                $months.StatusCode -eq 200 -and
                $frontend.StatusCode -eq 200 -and
                $frontend.Content -match "Hermes Finance"
            )
            if ($baseReady -and -not $RequireRecoverySurfaces) {
                return
            }
            if ($baseReady) {
                $accounts = Invoke-WebRequest `
                    -Uri "http://127.0.0.1:8000/api/accounts" `
                    -UseBasicParsing `
                    -TimeoutSec 2
                if ($accounts.StatusCode -ne 200) {
                    continue
                }

                $restoredMonths = @($months.Content | ConvertFrom-Json)
                if ($restoredMonths.Count -gt 0) {
                    $monthId = [int64]$restoredMonths[0].id
                    $dashboard = Invoke-WebRequest `
                        -Uri ("http://127.0.0.1:8000/api/months/{0}/dashboard" -f $monthId) `
                        -UseBasicParsing `
                        -TimeoutSec 2
                    if ($dashboard.StatusCode -ne 200) {
                        continue
                    }
                }
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
    if ($RecoveryReadiness -and -not $ExitAfterReady) {
        throw "Recovery readiness is a bounded smoke and requires -ExitAfterReady."
    }
    $uv = Get-RequiredCommand -Name "uv" -InstallHint "Install uv from https://docs.astral.sh/uv/."
    $powershell = Get-RequiredCommand -Name "powershell.exe" -InstallHint "Windows PowerShell is required to validate the prepared runtime."

    if (-not (Test-Path (Join-Path $backendDir "pyproject.toml") -PathType Leaf)) {
        throw "Backend project not found at '$backendDir'. Run this script from the Hermes Finance repository."
    }
    if (-not (Test-Path (Join-Path $frontendDir "package.json") -PathType Leaf)) {
        throw "Frontend project not found at '$frontendDir'. Run this script from the Hermes Finance repository."
    }

    Invoke-PreparedRuntimeValidation -PowerShell $powershell -Checkout $repoRoot

    Assert-PortAvailable -Port 8000

    $savedEnvironment = @{}
    foreach ($name in @(
        "HERMES_FINANCE_HOST",
        "HERMES_FINANCE_PORT",
        "HERMES_FINANCE_RELOAD",
        "HERMES_FINANCE_FRONTEND_DIST",
        "UV_OFFLINE",
        "PYTHONPATH"
    )) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        $env:HERMES_FINANCE_HOST = "127.0.0.1"
        $env:HERMES_FINANCE_PORT = "8000"
        $env:HERMES_FINANCE_RELOAD = "false"
        $env:HERMES_FINANCE_FRONTEND_DIST = $frontendDist
        $env:UV_OFFLINE = "1"
        $env:PYTHONPATH = ""

        Write-Host "Starting Hermes Finance production backend..." -ForegroundColor Cyan
        $backendProcess = Start-Process `
            -FilePath $uv `
            -ArgumentList @("run", "--locked", "--offline", "--no-sync", "hermes-finance-api") `
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

    Wait-ForProductionStack `
        -Backend $backendProcess `
        -RequireRecoverySurfaces ([bool]$RecoveryReadiness)
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
