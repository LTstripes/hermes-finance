[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RecoveryCheckout,
    [string]$RecoveryPoint,
    [string]$RecoverySha,
    [string]$ControlCheckout,
    [string]$RuntimeConfig,
    [string]$TargetProfile,
    [string]$TargetData,
    [string]$TargetDatabase,
    [string]$ProtectionState,
    [string]$ProtectionMode,
    [switch]$BootstrapOnly
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Assert-NoReparseComponents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Recovery bootstrap path contains a linked component."
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) {
            break
        }
        $next = $parent.FullName
        if ([string]::Equals($next, $current, [StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $current = $next
    }
}

function Assert-SafeMutableBoundary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [bool]$Directory
    )

    Assert-NoReparseComponents -Path $Path
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $root = Get-Item -LiteralPath $Path -Force
    if (($root.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Recovery bootstrap output boundary is linked."
    }
    if ($Directory -and -not $root.PSIsContainer) {
        throw "Recovery bootstrap output boundary has the wrong type."
    }
    if (-not $Directory -and $root.PSIsContainer) {
        throw "Recovery bootstrap output boundary has the wrong type."
    }
    if (-not $Directory) {
        return
    }

    $pending = New-Object System.Collections.Generic.Queue[string]
    $pending.Enqueue($root.FullName)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($child in @(Get-ChildItem -LiteralPath $current -Directory -Force)) {
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Recovery bootstrap output tree contains a linked directory."
            }
            $pending.Enqueue($child.FullName)
        }
        foreach ($child in @(Get-ChildItem -LiteralPath $current -File -Force)) {
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Recovery bootstrap output tree contains a linked file."
            }
        }
    }
}

function Write-PrivacySafeFailure {
    $payload = [ordered]@{
        status = "action_required"
        failure_stage = "bootstrap"
        action_required = "isolated recovery rehearsal was not completed; use a new target after resolving the failure"
    }
    Write-Output ($payload | ConvertTo-Json -Compress)
}

try {
    $checkout = [IO.Path]::GetFullPath($RecoveryCheckout).TrimEnd("\", "/")
    $scriptCheckout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..")).TrimEnd("\", "/")
    if (-not [string]::Equals($checkout, $scriptCheckout, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery bootstrap must execute from the selected checkout."
    }
    Assert-NoReparseComponents -Path $checkout
    $backend = Join-Path $checkout "backend"
    $frontend = Join-Path $checkout "frontend"
    foreach ($required in @(
        (Join-Path $backend "pyproject.toml"),
        (Join-Path $backend "uv.lock"),
        (Join-Path $frontend "package.json"),
        (Join-Path $frontend "package-lock.json")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Recovery bootstrap checkout is incomplete."
        }
    }
    Assert-SafeMutableBoundary -Path (Join-Path $backend ".venv") -Directory $true
    Assert-SafeMutableBoundary -Path (Join-Path $frontend "node_modules") -Directory $true
    Assert-SafeMutableBoundary -Path (Join-Path $frontend "dist") -Directory $true
    Assert-SafeMutableBoundary `
        -Path (Join-Path $checkout ".hermes-runtime-prepared.json") `
        -Directory $false

    if ($BootstrapOnly) {
        Write-Output '{"status":"bootstrap_verified"}'
        exit 0
    }
    foreach ($value in @(
        $RecoveryPoint,
        $RecoverySha,
        $ControlCheckout,
        $RuntimeConfig,
        $TargetProfile,
        $TargetData,
        $TargetDatabase,
        $ProtectionState,
        $ProtectionMode
    )) {
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Recovery bootstrap arguments are incomplete."
        }
    }

    $uvCommand = Get-Command "uv" -ErrorAction Stop
    $savedEnvironment = @{}
    foreach ($name in @(
        "UV_PROJECT_ENVIRONMENT",
        "UV_PROJECT",
        "UV_WORKING_DIR",
        "UV_LINK_MODE",
        "VIRTUAL_ENV"
    )) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    try {
        $env:UV_PROJECT_ENVIRONMENT = [IO.Path]::GetFullPath((Join-Path $backend ".venv"))
        $env:UV_LINK_MODE = "copy"
        Remove-Item Env:UV_PROJECT -ErrorAction SilentlyContinue
        Remove-Item Env:UV_WORKING_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            # Windows PowerShell promotes native stderr to ErrorRecord objects when
            # ErrorActionPreference is Stop. uv legitimately writes bootstrap progress
            # there, so discard that private/non-protocol stream without aborting.
            $ErrorActionPreference = "Continue"
            $output = & $uvCommand.Source `
                run `
                --project $backend `
                --locked `
                hermes-finance-recovery-rehearsal `
                --recovery-point $RecoveryPoint `
                --recovery-sha $RecoverySha `
                --recovery-checkout $checkout `
                --control-checkout $ControlCheckout `
                --runtime-config $RuntimeConfig `
                --target-profile $TargetProfile `
                --target-data $TargetData `
                --target-database $TargetDatabase `
                --protection-state $ProtectionState `
                --protection-mode $ProtectionMode 2>$null | Out-String
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
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
    if ([string]::IsNullOrWhiteSpace($output)) {
        Write-PrivacySafeFailure
        exit 2
    }
    try {
        $null = $output | ConvertFrom-Json -ErrorAction Stop
        Write-Output $output.Trim()
    }
    catch {
        Write-PrivacySafeFailure
        exit 2
    }
    exit $exitCode
}
catch {
    Write-PrivacySafeFailure
    exit 2
}
