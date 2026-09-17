<#
.SYNOPSIS
    Prepare an isolated Preview/UAT checkout at one explicit full commit SHA.

.DESCRIPTION
    This owner operation proves a candidate commit in the selected Hermes
    repository, creates or refreshes an independent Preview clone, validates
    the Preview data boundary, and invokes that candidate checkout's accepted
    Prepare and Validate operations. It never follows origin/main, starts the
    application, runs migrations directly, publishes a release, or changes
    Stable.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$CandidateSha,

    [Parameter(Mandatory = $true)]
    [string]$PreviewCheckout,

    [Parameter(Mandatory = $true)]
    [string]$PreviewDataDirectory,

    [Parameter(Mandatory = $true)]
    [string]$PreviewDatabase,

    [Parameter(Mandatory = $true)]
    [string]$StableCheckout,

    [Parameter(Mandatory = $true)]
    [string]$StableDataDirectory,

    [Parameter(Mandatory = $true)]
    [string]$StableDatabase,

    [string]$ControlCheckout,
    [string]$RepositoryUrl = "https://github.com/LTstripes/hermes-finance.git"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "prepare-preview-lib.ps1")

if ([string]::IsNullOrWhiteSpace($ControlCheckout)) {
    $ControlCheckout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

try {
    $result = Invoke-HermesPreviewPreparation `
        -CandidateSha $CandidateSha `
        -ControlCheckout $ControlCheckout `
        -PreviewCheckout $PreviewCheckout `
        -PreviewDataDirectory $PreviewDataDirectory `
        -PreviewDatabase $PreviewDatabase `
        -StableCheckout $StableCheckout `
        -StableDataDirectory $StableDataDirectory `
        -StableDatabase $StableDatabase `
        -RepositoryUrl $RepositoryUrl `
        -CommandRunner (New-HermesPreviewCommandRunner) `
        -CommandResolver (New-HermesPreviewCommandResolver)

    Write-Host "Preview UAT prepared: candidate_sha=$($result.CandidateSha)" -ForegroundColor Green
    Write-Host "Checkout: $($result.PreviewCheckout)"
    Write-Host "Data boundary: kind=$($result.SidecarKind)"
    Write-Host "No application start or database migration was performed."
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
