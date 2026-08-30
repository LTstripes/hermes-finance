<#
.SYNOPSIS
    Publish an annotated Git tag and GitHub Release from an exact origin/main SHA.

.DESCRIPTION
    Windows PowerShell 5.1 release helper for LTstripes/hermes-finance.

    It fetches origin/main, requires the supplied full SHA, requires completed
    exact-main GitHub Actions CI, creates an annotated tag on that commit,
    pushes only refs/tags/<tag>, then creates a published GitHub Release from
    the existing tag.

    It never force-updates a tag, never pushes a branch, never creates commits,
    and never reads .env, tokens, or private financial data.

.PARAMETER Version
    Release version as X.Y.Z or vX.Y.Z. Normalized to tag vX.Y.Z.

.PARAMETER ExpectedMainSha
    Full 40-character SHA. origin/main must match this after fetch.

.PARAMETER ReleaseNotes
    Path to Markdown release notes. The file is passed to GitHub as-is.

.PARAMETER Title
    Optional GitHub Release / annotated-tag title. Defaults to
    "Hermes Finance <X.Y.Z>".

.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release.ps1 `
        -Version 0.7.0 `
        -ExpectedMainSha 0123456789abcdef0123456789abcdef01234567 `
        -ReleaseNotes .\docs\release-notes-0.7.0.md
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedMainSha,

    [Parameter(Mandatory = $true)]
    [string]$ReleaseNotes,

    [string]$Title
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$libraryPath = Join-Path $PSScriptRoot "release-lib.ps1"
if (-not (Test-Path -LiteralPath $libraryPath -PathType Leaf)) {
    Write-Host "ERROR: Release helper library not found at '$libraryPath'." -ForegroundColor Red
    exit 1
}

. $libraryPath

try {
    $result = Invoke-HermesRelease `
        -Version $Version `
        -ExpectedMainSha $ExpectedMainSha `
        -ReleaseNotes $ReleaseNotes `
        -Title $Title `
        -CommandRunner (New-HermesDefaultCommandRunner) `
        -CommandResolver (New-HermesDefaultCommandResolver)

    Write-Host "Published Hermes Finance $($result.Version)" -ForegroundColor Green
    Write-Host "Tag: $($result.Tag)"
    Write-Host "Commit: $($result.Sha)"
    if ([bool]$result.ReusedExistingTag) {
        Write-Host "Tag source: reused existing annotated tag"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$result.ReleaseUrl)) {
        Write-Host "Release: $($result.ReleaseUrl)"
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
