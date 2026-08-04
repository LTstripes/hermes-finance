[CmdletBinding()]
param(
    [switch]$ExitAfterReady
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$backendProcess = $null
$frontendProcess = $null
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

function Wait-ForDevelopmentStack {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend,
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Frontend
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        Assert-ProcessRunning -Process $Backend -Name "Backend"
        Assert-ProcessRunning -Process $Frontend -Name "Frontend"

        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:5173/api/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            # Both processes are still alive, so allow startup to continue.
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Development stack did not become ready within 45 seconds."
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
    $node = Get-RequiredCommand -Name "node.exe" -InstallHint "Install Node.js 22.22 or newer from https://nodejs.org/."

    if (-not (Test-Path (Join-Path $backendDir "pyproject.toml") -PathType Leaf)) {
        throw "Backend project not found at '$backendDir'. Run this script from the Hermes Finance repository."
    }
    if (-not (Test-Path (Join-Path $frontendDir "package.json") -PathType Leaf)) {
        throw "Frontend project not found at '$frontendDir'. Run this script from the Hermes Finance repository."
    }
    if (-not (Test-Path (Join-Path $frontendDir "node_modules") -PathType Container)) {
        throw "Frontend dependencies are missing. Run 'cd frontend' and then 'npm ci'."
    }
    $viteEntry = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
    if (-not (Test-Path $viteEntry -PathType Leaf)) {
        throw "Vite is missing from frontend dependencies. Run 'cd frontend' and then 'npm ci'."
    }

    Assert-PortAvailable -Port 8000
    Assert-PortAvailable -Port 5173

    Write-Host "Starting Hermes Finance backend and frontend..." -ForegroundColor Cyan
    $pythonPathWasSet = Test-Path Env:PYTHONPATH
    $originalPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = ""
        $backendProcess = Start-Process `
            -FilePath $uv `
            -ArgumentList @("run", "hermes-finance-api") `
            -WorkingDirectory $backendDir `
            -NoNewWindow `
            -PassThru
    }
    finally {
        if ($pythonPathWasSet) {
            $env:PYTHONPATH = $originalPythonPath
        }
        else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }
    $frontendProcess = Start-Process `
        -FilePath $node `
        -ArgumentList @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1") `
        -WorkingDirectory $frontendDir `
        -NoNewWindow `
        -PassThru

    Wait-ForDevelopmentStack -Backend $backendProcess -Frontend $frontendProcess

    Write-Host "Hermes Finance is ready: http://127.0.0.1:5173" -ForegroundColor Green
    if ($ExitAfterReady) {
        Write-Host "Readiness smoke test passed." -ForegroundColor Green
    }
    else {
        Write-Host "Press Ctrl+C to stop both processes." -ForegroundColor DarkGray

        while ($true) {
            Assert-ProcessRunning -Process $backendProcess -Name "Backend"
            Assert-ProcessRunning -Process $frontendProcess -Name "Frontend"
            Start-Sleep -Seconds 1
        }
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    Stop-ProcessTree -Process $frontendProcess -Name "frontend"
    Stop-ProcessTree -Process $backendProcess -Name "backend"
}

exit $exitCode
