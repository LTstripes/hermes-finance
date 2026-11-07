<# Post the owner release-control comment after exact-main preflight. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$DryRun
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "release-lib.ps1")
. (Join-Path $PSScriptRoot "release-request-lib.ps1")
Submit-HermesReleaseRequest -Version $Version -RepoRoot (Join-Path $PSScriptRoot "..") -DryRun:$DryRun
