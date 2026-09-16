<#
.SYNOPSIS
    Update one explicit Stable checkout to one published immutable release.

.DESCRIPTION
    This is a small owner operation intended to run from a trusted control
    checkout, outside the mutable Stable checkout. It proves the requested
    published annotated release, creates a verified SQLite backup, fetches only
    that tag, switches Stable to its exact commit, then invokes the target
    checkout's accepted Prepare and Validate operations.

    It never selects latest, follows main, updates another checkout, starts
    Hermes, runs migrations, creates a tag/release, or attempts rollback.

.PARAMETER StableCheckout
    Explicit path to the existing Stable Git checkout.

.PARAMETER TargetVersion
    Owner-selected stable semantic version as X.Y.Z or vX.Y.Z.

.PARAMETER DatabasePath
    Optional absolute path to the production SQLite database. When omitted,
    HERMES_FINANCE_DATABASE_PATH is used if present; otherwise the existing
    checkout-relative data/finance.db contract is used.

.PARAMETER BackupDirectory
    Optional backup directory. When omitted, backups is placed beside the
    resolved database path, matching the existing backup contract.

.PARAMETER ControlCheckout
    Optional trusted checkout containing this script and the accepted backup
    helper. Defaults to the checkout containing this script.

.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
        -StableCheckout 'C:\Hermes\stable' `
        -TargetVersion 0.8.3
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [Alias("Checkout")]
    [string]$StableCheckout,

    [Parameter(Mandatory = $true, Position = 1)]
    [Alias("Version")]
    [string]$TargetVersion,

    [Alias("Database")]
    [string]$DatabasePath,

    [Alias("BackupDir")]
    [string]$BackupDirectory,

    [string]$ControlCheckout
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$scriptDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$controlRoot = if ([string]::IsNullOrWhiteSpace($ControlCheckout)) {
    [IO.Path]::GetFullPath((Join-Path $scriptDirectory ".."))
}
else {
    [IO.Path]::GetFullPath($ControlCheckout)
}

$releaseLibrary = Join-Path $scriptDirectory "release-lib.ps1"
$releaseRequestLibrary = Join-Path $scriptDirectory "release-request-lib.ps1"
$updateLibrary = Join-Path $scriptDirectory "update-stable-lib.ps1"
foreach ($library in @($releaseLibrary, $releaseRequestLibrary, $updateLibrary)) {
    if (-not (Test-Path -LiteralPath $library -PathType Leaf)) {
        Write-Host "ERROR: Stable update helper library is missing: $library" -ForegroundColor Red
        exit 1
    }
}

. $releaseLibrary
. $releaseRequestLibrary
. $updateLibrary

try {
    $result = Invoke-HermesStableUpdate `
        -StableCheckout $StableCheckout `
        -TargetVersion $TargetVersion `
        -DatabasePath $DatabasePath `
        -BackupDirectory $BackupDirectory `
        -ControlCheckout $controlRoot `
        -CommandRunner (New-HermesDefaultCommandRunner) `
        -CommandResolver (New-HermesDefaultCommandResolver)

    if ($result.Status -eq "no-op") {
        Write-Host "Stable update: no-op; already at published $($result.TargetTag) ($($result.TargetCommit))." -ForegroundColor Green
    }
    else {
        Write-Host "Stable update: $($result.TargetTag) ($($result.TargetCommit)) is prepared and validated." -ForegroundColor Green
        Write-Host "Backup: $($result.BackupId)"
    }
    Write-Host "No application start or database migration was performed."
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
