# Static/syntax contract tests for the GitHub-native release entrypoint.
# No network calls, tags, releases, credentials or private runtime data.

[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$entrypointPath = Join-Path $repoRoot "scripts\release-automation.ps1"
$workflowPath = Join-Path $repoRoot ".github\workflows\release.yml"

foreach ($required in @($entrypointPath, $workflowPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required HYG-04 file is missing: $required"
    }
}

$script:Passed = 0
$script:Failed = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Case {
    param([Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][scriptblock]$Script)
    try {
        & $Script
        $script:Passed += 1
        Write-Host "PASS: $Name" -ForegroundColor Green
    }
    catch {
        $script:Failed += 1
        Write-Host "FAIL: $Name" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
}

Invoke-Case "release automation entrypoint parses in Windows PowerShell" {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $entrypointPath,
        [ref]$tokens,
        [ref]$errors
    )
    $parseErrors = @($errors)
    if ($parseErrors.Count -ne 0) {
        $messages = @($parseErrors | ForEach-Object { $_.Message })
        throw "release-automation.ps1 parse errors: $([string]::Join('; ', $messages))"
    }
}

$workflow = [IO.File]::ReadAllText($workflowPath)

Invoke-Case "workflow trigger is narrow issue_comment created" {
    Assert-True -Condition ($workflow -match '(?m)^\s{2}issue_comment:\s*$') -Message "release.yml must use issue_comment trigger."
    Assert-True -Condition ($workflow -match '(?m)^\s{4}types:\s*\[created\]\s*$') -Message "release.yml must accept created comments only."
    Assert-True -Condition ($workflow -notmatch '(?m)^\s{2}workflow_dispatch:\s*$') -Message "release.yml must not depend on manual workflow_dispatch."
    Assert-True -Condition ($workflow -notmatch '(?m)^\s{2}push:\s*$') -Message "release.yml must not auto-release on push."
}

Invoke-Case "workflow accepts only owner request on control issue 124" {
    Assert-True -Condition ($workflow -match 'github\.event\.issue\.number\s*==\s*124') -Message "release.yml must bind the trigger to control issue #124."
    Assert-True -Condition ($workflow -match 'github\.event\.comment\.user\.login\s*==\s*github\.repository_owner') -Message "release.yml must require owner-authored comment."
    Assert-True -Condition ($workflow -match 'github\.actor\s*==\s*github\.repository_owner') -Message "release.yml must require owner actor."
    Assert-True -Condition ($workflow -match "startsWith\(github\.event\.comment\.body, '/release'\)") -Message "release.yml must gate the release command prefix."
    Assert-True -Condition ($workflow -match '(?m)^\s{12}-ControlIssueNumber 124 `\s*$') -Message "release entrypoint must receive control issue #124 explicitly."
}

Invoke-Case "workflow uses built-in token and minimal write permissions" {
    Assert-True -Condition ($workflow -match '(?m)^\s{6}actions:\s*read\s*$') -Message "release job must have actions: read."
    Assert-True -Condition ($workflow -match '(?m)^\s{6}contents:\s*write\s*$') -Message "release job must have contents: write."
    Assert-True -Condition ($workflow -match '(?m)^\s{2}contents:\s*read\s*$') -Message "workflow default must remain contents: read."
    Assert-True -Condition ($workflow -match 'GH_TOKEN:\s*\$\{\{\s*github\.token\s*\}\}') -Message "release job must use the built-in github.token."

    foreach ($forbidden in @(
        'issues:\s*write',
        'pull-requests:\s*write',
        'packages:\s*write',
        'deployments:\s*write',
        'id-token:\s*write',
        'actions:\s*write'
    )) {
        Assert-True -Condition ($workflow -notmatch $forbidden) -Message "release.yml contains forbidden permission matching '$forbidden'."
    }
}

Invoke-Case "workflow passes event payload through environment variables" {
    Assert-True -Condition ($workflow -match 'HERMES_RELEASE_REQUEST_BODY:\s*\$\{\{\s*github\.event\.comment\.body\s*\}\}') -Message "Comment body must be passed through an environment variable."
    Assert-True -Condition ($workflow -notmatch '(?m)^\s*& powershell.*github\.event\.comment\.body') -Message "Untrusted comment body must not be interpolated directly into a shell command."
}

Write-Host "Release workflow contract tests: $($script:Passed) passed, $($script:Failed) failed."
if ($script:Failed -ne 0) {
    exit 1
}
