<#
.SYNOPSIS
    Execute the GitHub-native owner-triggered Hermes Finance release path.

.DESCRIPTION
    Validates the permanent release-control issue event, parses the exact
    /release request, verifies repository version identity and canonical notes,
    then delegates publication to the same guarded release library used by
    scripts/release.ps1.

    The script never reads production runtime data, .env, finance databases,
    backups or owner-private payloads.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RequestBody,
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [Parameter(Mandatory = $true)]
    [string]$Actor,
    [Parameter(Mandatory = $true)]
    [string]$CommentAuthor,
    [Parameter(Mandatory = $true)]
    [int]$IssueNumber,
    [Parameter(Mandatory = $true)]
    [int]$ControlIssueNumber,
    [Parameter(Mandatory = $true)]
    [string]$EventName,
    [Parameter(Mandatory = $true)]
    [string]$EventAction,
    [string]$RepoRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$requestLibraryPath = Join-Path $PSScriptRoot "release-request-lib.ps1"
$releaseLibraryPath = Join-Path $PSScriptRoot "release-lib.ps1"
foreach ($libraryPath in @($requestLibraryPath, $releaseLibraryPath)) {
    if (-not (Test-Path -LiteralPath $libraryPath -PathType Leaf)) {
        throw "Required release library not found: $libraryPath"
    }
}

. $requestLibraryPath
. $releaseLibraryPath

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}
else {
    $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
}

Assert-HermesReleaseRequestProvenance `
    -Repository $Repository `
    -Actor $Actor `
    -CommentAuthor $CommentAuthor `
    -IssueNumber $IssueNumber `
    -ControlIssueNumber $ControlIssueNumber `
    -EventName $EventName `
    -EventAction $EventAction

$request = Get-HermesReleaseRequest -RequestBody $RequestBody
$identity = Assert-HermesReleaseIdentity -RepoRoot $RepoRoot -Version $request.Version

Write-HermesReleaseStep "Release request accepted from owner control issue #$ControlIssueNumber"
Write-HermesReleaseStep "Repository identity is $($request.Version); canonical notes found"

$result = Invoke-HermesRelease `
    -Version $request.Version `
    -ExpectedMainSha $request.ExpectedMainSha `
    -ReleaseNotes $identity.ReleaseNotes `
    -RepoRoot $RepoRoot `
    -CommandRunner (New-HermesDefaultCommandRunner) `
    -CommandResolver (New-HermesDefaultCommandResolver)

function Get-HermesLsRemoteFirstSha {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $output = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Label read-back failed: $([string]::Join(' ', @($output)))"
    }
    $text = [string]::Join("`n", @($output))
    $line = @($text -split "\r?\n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
    if ($line.Count -eq 0) {
        throw "$Label read-back returned no ref."
    }
    $sha = (([string]$line[0]) -split "\s+")[0].ToLowerInvariant()
    if ($sha -notmatch "^[0-9a-f]{40}$") {
        throw "$Label read-back returned malformed SHA '$sha'."
    }
    return $sha
}

$tagObjectSha = Get-HermesLsRemoteFirstSha `
    -Arguments @("-C", $RepoRoot, "ls-remote", "--tags", "origin", "refs/tags/$($result.Tag)") `
    -Label "Tag object"
$peeledCommitSha = Get-HermesLsRemoteFirstSha `
    -Arguments @("-C", $RepoRoot, "ls-remote", "--tags", "origin", "refs/tags/$($result.Tag)^{}") `
    -Label "Peeled tag"
$mainShaAfter = Get-HermesLsRemoteFirstSha `
    -Arguments @("-C", $RepoRoot, "ls-remote", "origin", "refs/heads/main") `
    -Label "main"

if ($peeledCommitSha -ne $request.ExpectedMainSha) {
    throw "Final peeled tag commit is $peeledCommitSha, expected $($request.ExpectedMainSha)."
}
if ($mainShaAfter -ne $request.ExpectedMainSha) {
    throw "main moved during release: final main is $mainShaAfter, expected $($request.ExpectedMainSha)."
}
if ($tagObjectSha -eq $peeledCommitSha) {
    throw "Final tag read-back is not annotated: tag object SHA equals peeled commit SHA."
}

$releaseJson = & gh release view $result.Tag --repo $Repository --json "name,tagName,isDraft,isPrerelease,url" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "GitHub Release read-back failed: $([string]::Join(' ', @($releaseJson)))"
}
$release = ([string]::Join("`n", @($releaseJson))) | ConvertFrom-Json
$expectedTitle = "Hermes Finance $($request.Version)"
if ([string]$release.tagName -ne $result.Tag) {
    throw "Final GitHub Release tag '$($release.tagName)' does not match $($result.Tag)."
}
if ([bool]$release.isDraft -or [bool]$release.isPrerelease) {
    throw "Final GitHub Release is draft=$($release.isDraft) prerelease=$($release.isPrerelease); expected published stable release."
}
if ([string]$release.name -ne $expectedTitle) {
    throw "Final GitHub Release title '$($release.name)' does not match '$expectedTitle'."
}

$releaseState = "published"
$summaryPath = [string]$env:GITHUB_STEP_SUMMARY
if (-not [string]::IsNullOrWhiteSpace($summaryPath)) {
    $summaryLines = @(
        "# Hermes Finance guarded release",
        "",
        "- Version: ``$($request.Version)``",
        "- Tag: ``$($result.Tag)``",
        "- Tag object: ``$tagObjectSha``",
        "- Peeled commit: ``$peeledCommitSha``",
        "- main after publication: ``$mainShaAfter``",
        "- Release title: ``$($release.name)``",
        "- Release state: ``$releaseState``",
        "- Release URL: $($release.url)",
        "- Control issue: #$ControlIssueNumber",
        "- Request actor: ``$Actor``"
    )
    [IO.File]::AppendAllText(
        $summaryPath,
        ([string]::Join("`n", $summaryLines) + "`n"),
        (New-Object System.Text.UTF8Encoding $false)
    )
}

Write-Host "Guarded release verified." -ForegroundColor Green
Write-Host "Version: $($request.Version)"
Write-Host "Tag: $($result.Tag)"
Write-Host "Tag object: $tagObjectSha"
Write-Host "Peeled commit: $peeledCommitSha"
Write-Host "main: $mainShaAfter"
Write-Host "Release: $($release.url)"
