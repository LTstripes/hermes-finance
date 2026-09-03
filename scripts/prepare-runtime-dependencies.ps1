[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Checkout,
    [switch]$Prepare,
    [switch]$Repair
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ($Prepare -and $Repair) {
    throw "Choose either -Prepare or -Repair, not both."
}

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

function Invoke-CapturedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    Push-Location $WorkingDirectory
    try {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = & $FilePath @ArgumentList 2>&1 | Out-String
            [pscustomobject]@{
                ExitCode = $LASTEXITCODE
                Output = $output
            }
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
    }
    finally {
        Pop-Location
    }
}

function Get-DependencyStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Uv,
        [Parameter(Mandatory = $true)]
        [string]$Npm
    )

    $backend = Join-Path $Root "backend"
    $frontend = Join-Path $Root "frontend"
    foreach ($required in @(
        (Join-Path $backend "pyproject.toml"),
        (Join-Path $backend "uv.lock"),
        (Join-Path $frontend "package.json"),
        (Join-Path $frontend "package-lock.json")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required dependency metadata is missing: $required"
        }
    }

    $backendCheck = Invoke-CapturedCommand `
        -FilePath $Uv `
        -WorkingDirectory $backend `
        -ArgumentList @("sync", "--locked", "--dry-run", "--offline")
    if ($backendCheck.ExitCode -ne 0) {
        throw "Backend dependency check failed: $($backendCheck.Output.Trim())"
    }

    $backendNeedsPreparation = $backendCheck.Output -match "(?im)^\s*Would\s+(create|download|install|remove|uninstall|update|reinstall|build)\b"
    $backendMessage = if ($backendNeedsPreparation) {
        "needs preparation"
    }
    else {
        "ready"
    }

    $nodeModules = Join-Path $frontend "node_modules"
    $frontendNeedsPreparation = -not (Test-Path -LiteralPath $nodeModules -PathType Container)
    $frontendMessage = if ($frontendNeedsPreparation) {
        "needs preparation: frontend/node_modules is missing"
    }
    else {
        $frontendCheck = Invoke-CapturedCommand `
            -FilePath $Npm `
            -WorkingDirectory $frontend `
            -ArgumentList @("ls", "--all", "--depth=0", "--json", "--omit=optional", "--loglevel=silent")
        try {
            $status = $frontendCheck.Output | ConvertFrom-Json
        }
        catch {
            throw "Frontend dependency check returned invalid JSON: $($_.Exception.Message)"
        }
        $problems = @(
            if ($status.PSObject.Properties.Name -contains "problems") {
                $status.problems
            }
        )
        if ($problems.Count -gt 0 -or $frontendCheck.ExitCode -ne 0) {
            $frontendNeedsPreparation = $true
            "needs preparation: $($problems | Select-Object -First 1)"
        }
        else {
            "ready"
        }
    }

    [pscustomobject]@{
        BackendReady = -not $backendNeedsPreparation
        FrontendReady = -not $frontendNeedsPreparation
        BackendMessage = $backendMessage
        FrontendMessage = $frontendMessage
    }
}

try {
    $resolvedCheckout = [IO.Path]::GetFullPath($Checkout)
    if (-not (Test-Path -LiteralPath $resolvedCheckout -PathType Container)) {
        throw "Checkout does not exist: $resolvedCheckout"
    }

    $uv = Get-RequiredCommand -Name "uv" -InstallHint "Install uv from https://docs.astral.sh/uv/."
    $npm = Get-RequiredCommand -Name "npm.cmd" -InstallHint "Install Node.js 22.22 or newer from https://nodejs.org/."
    $status = $null
    if (-not $Repair) {
        $status = Get-DependencyStatus -Root $resolvedCheckout -Uv $uv -Npm $npm
    }

    if ($Repair -or ($Prepare -and -not $status.BackendReady)) {
        Write-Host $(if ($Repair) { "Repairing locked backend dependencies..." } else { "Preparing locked backend dependencies..." }) -ForegroundColor Cyan
        Push-Location (Join-Path $resolvedCheckout "backend")
        try {
            & $uv sync --locked
            if ($LASTEXITCODE -ne 0) {
                throw "Backend dependency preparation failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }

    if ($Repair -or ($Prepare -and -not $status.FrontendReady)) {
        Write-Host $(if ($Repair) { "Repairing locked frontend dependencies..." } else { "Preparing locked frontend dependencies..." }) -ForegroundColor Cyan
        Push-Location (Join-Path $resolvedCheckout "frontend")
        try {
            & $npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend dependency preparation failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }

    if ($Prepare -or $Repair) {
        $status = Get-DependencyStatus -Root $resolvedCheckout -Uv $uv -Npm $npm
    }

    Write-Output "backend=$($status.BackendMessage)"
    Write-Output "frontend=$($status.FrontendMessage)"
    if (-not $status.BackendReady -or -not $status.FrontendReady) {
        exit 2
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
