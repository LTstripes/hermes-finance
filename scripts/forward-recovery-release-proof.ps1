[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Checkout,
    [Parameter(Mandatory=$true)][string]$ExpectedSha,
    [Parameter(Mandatory=$true)][string]$Version
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release-lib.ps1')
. (Join-Path $PSScriptRoot 'release-request-lib.ps1')
. (Join-Path $PSScriptRoot 'update-stable-lib.ps1')
try {
    $resolver = New-HermesDefaultCommandResolver
    $context = [pscustomobject]@{
        RepoRoot = $Checkout
        CommandRunner = (New-HermesDefaultCommandRunner)
        GitPath = (Resolve-HermesToolPath -CommandResolver $resolver -Name 'git' -InstallHint 'Git required')
        GhPath = (Resolve-HermesToolPath -CommandResolver $resolver -Name 'gh' -InstallHint 'GitHub CLI required')
        PushUrl = $null
    }
    Assert-HermesStableOrigin -Context $context
    $parts = Convert-HermesStableVersionParts -Version $Version -Label 'recovery release'
    $target = Assert-HermesStableTargetRelease -Context $context -Tag $parts.Tag -Version $parts
    if ($target.CommitSha -cne $ExpectedSha) { throw 'recovery release SHA mismatch' }
    Assert-HermesStableTargetCodeIdentity -Context $context -Target $target
    & (Join-Path $Checkout 'scripts\prepare-runtime.ps1') -Checkout $Checkout -Validate
    if ($LASTEXITCODE -ne 0) { throw 'recovery code is not prepared' }
    Write-Output 'recovery-release-proof=verified'
} catch {
    Write-Output 'recovery-release-proof=refused'
    exit 1
}
