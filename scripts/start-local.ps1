[CmdletBinding()]
param(
    [switch]$ExitAfterReady,
    [switch]$RecoveryReadiness
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "recovery-runtime-safety.ps1")

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

function Test-RecoveryListenerOwned {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend
    )

    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop)
    $processRows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    return Test-HermesLoopbackListenerOwnership `
        -RootProcessId $Backend.Id `
        -Listeners $listeners `
        -ProcessRows $processRows
}

function Test-RecoveryResponseOwned {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend,
        [Parameter(Mandatory = $true)]
        [object]$Response,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedRecoveryToken,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedDatabaseIdentity,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCheckoutSha
    )

    return (
        (Test-RecoveryListenerOwned -Backend $Backend) -and
        (Test-HermesRecoveryHeaders `
            -Response $Response `
            -ExpectedToken $ExpectedRecoveryToken `
            -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
            -ExpectedCheckoutSha $ExpectedCheckoutSha)
    )
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
        [bool]$RequireRecoverySurfaces,
        [string]$ExpectedRecoveryToken,
        [string]$ExpectedDatabaseIdentity,
        [string]$ExpectedCheckoutSha
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        Assert-ProcessRunning -Process $Backend -Name "Backend"

        try {
            if ($RequireRecoverySurfaces -and -not (Test-RecoveryListenerOwned -Backend $Backend)) {
                Start-Sleep -Milliseconds 250
                continue
            }
            $health = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/api/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            if (
                $RequireRecoverySurfaces -and
                -not (Test-RecoveryResponseOwned `
                    -Backend $Backend `
                    -Response $health `
                    -ExpectedRecoveryToken $ExpectedRecoveryToken `
                    -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
                    -ExpectedCheckoutSha $ExpectedCheckoutSha)
            ) {
                continue
            }
            $months = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/api/months" `
                -UseBasicParsing `
                -TimeoutSec 2
            if (
                $RequireRecoverySurfaces -and
                -not (Test-RecoveryResponseOwned `
                    -Backend $Backend `
                    -Response $months `
                    -ExpectedRecoveryToken $ExpectedRecoveryToken `
                    -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
                    -ExpectedCheckoutSha $ExpectedCheckoutSha)
            ) {
                continue
            }
            $frontend = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/" `
                -UseBasicParsing `
                -TimeoutSec 2
            if (
                $RequireRecoverySurfaces -and
                -not (Test-RecoveryResponseOwned `
                    -Backend $Backend `
                    -Response $frontend `
                    -ExpectedRecoveryToken $ExpectedRecoveryToken `
                    -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
                    -ExpectedCheckoutSha $ExpectedCheckoutSha)
            ) {
                continue
            }
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
                if (
                    $accounts.StatusCode -ne 200 -or
                    -not (Test-RecoveryResponseOwned `
                        -Backend $Backend `
                        -Response $accounts `
                        -ExpectedRecoveryToken $ExpectedRecoveryToken `
                        -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
                        -ExpectedCheckoutSha $ExpectedCheckoutSha)
                ) {
                    continue
                }

                $restoredMonths = @($months.Content | ConvertFrom-Json)
                if ($restoredMonths.Count -gt 0) {
                    $monthId = [int64]$restoredMonths[0].id
                    $dashboard = Invoke-WebRequest `
                        -Uri ("http://127.0.0.1:8000/api/months/{0}/dashboard" -f $monthId) `
                        -UseBasicParsing `
                        -TimeoutSec 2
                    if (
                        $dashboard.StatusCode -ne 200 -or
                        -not (Test-RecoveryResponseOwned `
                            -Backend $Backend `
                            -Response $dashboard `
                            -ExpectedRecoveryToken $ExpectedRecoveryToken `
                            -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
                            -ExpectedCheckoutSha $ExpectedCheckoutSha)
                    ) {
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
    if ($RecoveryReadiness) {
        foreach ($requiredCommand in @("Get-NetTCPConnection", "Get-CimInstance")) {
            if ($null -eq (Get-Command $requiredCommand -ErrorAction SilentlyContinue)) {
                throw "Recovery readiness process ownership checks are unavailable."
            }
        }
        if (
            $env:HERMES_FINANCE_RECOVERY_READINESS_TOKEN -notmatch "^[0-9a-f]{64}$" -or
            $env:HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY -notmatch "^[0-9a-f]{64}$" -or
            $env:HERMES_FINANCE_RECOVERY_CHECKOUT_SHA -notmatch "^[0-9a-f]{40}$"
        ) {
            throw "Recovery readiness identity is missing or invalid."
        }
        $expectedProjectEnvironment = [IO.Path]::GetFullPath((Join-Path $backendDir ".venv"))
        $actualProjectEnvironment = [IO.Path]::GetFullPath($env:UV_PROJECT_ENVIRONMENT)
        if (-not [string]::Equals(
            $actualProjectEnvironment,
            $expectedProjectEnvironment,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Recovery runtime environment is not isolated to the selected checkout."
        }
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
        "UV_PROJECT_ENVIRONMENT",
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
        $env:UV_PROJECT_ENVIRONMENT = [IO.Path]::GetFullPath((Join-Path $backendDir ".venv"))
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
        -RequireRecoverySurfaces ([bool]$RecoveryReadiness) `
        -ExpectedRecoveryToken $env:HERMES_FINANCE_RECOVERY_READINESS_TOKEN `
        -ExpectedDatabaseIdentity $env:HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY `
        -ExpectedCheckoutSha $env:HERMES_FINANCE_RECOVERY_CHECKOUT_SHA
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
