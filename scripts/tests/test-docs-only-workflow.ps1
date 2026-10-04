# Static contract tests for the docs-only pull-request gate.
# No network calls, runtime startup, credentials or private data.

[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$workflowPath = Join-Path $repoRoot ".github\workflows\ci.yml"
$releasePath = Join-Path $repoRoot ".github\workflows\release.yml"
$evidencePath = Join-Path $repoRoot ".github\workflows\ui-v2-evidence.yml"
foreach ($path in @($workflowPath, $releasePath, $evidencePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Workflow not found: $path"
    }
}

$workflow = [IO.File]::ReadAllText($workflowPath)
$release = [IO.File]::ReadAllText($releasePath)
$evidence = [IO.File]::ReadAllText($evidencePath)
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

function Get-Job {
    param([string]$JobId)
    $pattern = '(?ms)^  ' + [regex]::Escape($JobId) + ':\s*.*?(?=^  [A-Za-z0-9-]+:\s*$|\z)'
    $match = [regex]::Match($workflow, $pattern)
    if (-not $match.Success) {
        throw "Could not isolate job $JobId."
    }
    return $match.Value
}

Invoke-Case "workflow trigger is not path-filtered" {
    $onBlock = [regex]::Match($workflow, '(?ms)^on:\s*.*?(?=^permissions:\s*$)').Value
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace($onBlock)) -Message "Could not isolate the workflow trigger."
    Assert-True -Condition ($onBlock -match '(?m)^  push:\s*$') -Message "CI must retain a push trigger."
    Assert-True -Condition ($onBlock -match '(?m)^    branches: \[main\]\s*$') -Message "Canonical main pushes stay in CI."
    Assert-True -Condition ($onBlock -match '(?m)^  pull_request:\s*$') -Message "CI must retain a pull_request trigger."
    Assert-True -Condition ($onBlock -notmatch 'paths-ignore') -Message "Workflow-level paths-ignore leaves a required check pending."
    Assert-True -Condition ($onBlock -notmatch '(?m)^\s*paths:') -Message "Workflow-level paths filters leave a required check pending."
}

Invoke-Case "classification is recomputed from the current pull request commits" {
    $classify = Get-Job "docs-only-classify"
    Assert-True -Condition ($classify -match "if: github\.event_name == 'pull_request'") -Message "Classification is pull-request-only; main stays full."
    Assert-True -Condition ($classify -match 'scripts/docs_only_ci\.py classify') -Message "The classifier must read the diff itself."
    Assert-True -Condition ($classify -match 'github\.event\.pull_request\.base\.sha') -Message "The base SHA must come from the current event."
    Assert-True -Condition ($classify -match 'github\.event\.pull_request\.head\.sha') -Message "The head SHA must come from the current event."
    Assert-True -Condition ($classify -notmatch 'actions/cache@') -Message "A cached mode would be stale after synchronize."
    Assert-True -Condition ($workflow -match 'python3 scripts/tests/test-docs-only-ci\.py') -Message "Privacy must run the docs-only regressions."
}

Invoke-Case "product suites run unless classification succeeded as docs-only" {
    $condition = "github.event_name != 'pull_request' || needs.docs-only-classify.result != 'success' || needs.docs-only-classify.outputs.mode != 'docs-only'"
    foreach ($jobId in @(
        "backend-quality",
        "backend-tests",
        "backend-timezone-windows",
        "frontend",
        "g04-browser",
        "release-safety",
        "windows-production-smoke"
    )) {
        $job = Get-Job $jobId
        Assert-True -Condition ($job -match 'needs: docs-only-classify') -Message "$jobId must observe the classifier."
        Assert-True -Condition ($job -match 'always\(\)') -Message "$jobId must still start when the classifier is skipped on main."
        Assert-True -Condition ($job -match '!cancelled\(\)') -Message "$jobId must not start after cancellation."
        Assert-True -Condition ($job -match [regex]::Escape($condition)) -Message "$jobId must fail closed to the full suite."
    }
    $launcher = Get-Job "windows-launcher-paths"
    Assert-True -Condition ($launcher -notmatch 'docs-only') -Message "The existing launcher path filter stays unchanged."
    $visual = Get-Job "visual-audit"
    Assert-True -Condition ($visual -match "github\.event_name == 'push' \|\| needs\.visual-audit-paths\.outputs\.run == 'true'") -Message "The visual audit gate stays intact."
    Assert-True -Condition ($visual -match 'scripts/ui_evidence_identity\.py trees') -Message "Exact-head identity proof stays inside the visual audit."
}

Invoke-Case "docs-only success cannot be a skipped or failed retained check" {
    $fast = Get-Job "docs-fast-path"
    Assert-True -Condition ($fast -match 'name: Documentation fast path') -Message "The terminal check must name the docs-only result."
    Assert-True -Condition ($fast -match 'scripts/docs_only_ci\.py verdict') -Message "The fast path must recompute the diff and judge job results."
    Assert-True -Condition ($fast -match 'github\.event\.pull_request\.base\.sha') -Message "The verdict must use the current base SHA."
    Assert-True -Condition ($fast -match 'github\.event\.pull_request\.head\.sha') -Message "The verdict must use the current head SHA."
    foreach ($jobId in @(
        "privacy",
        "visual-audit-paths",
        "windows-launcher-paths",
        "backend-quality",
        "frontend",
        "g04-browser",
        "visual-audit",
        "release-safety",
        "windows-production-smoke",
        "windows-launcher-safety"
    )) {
        $needle = '--job "' + $jobId + '=${{ needs.' + $jobId + '.result }}"'
        Assert-True -Condition ($fast.Contains($needle)) -Message "Fast path must read $jobId."
    }
    Assert-True -Condition ($workflow -match '(?ms)^  release-safety:.*?test-docs-only-workflow\.ps1') -Message "Release safety must verify this contract on the full path."
    Assert-True -Condition ($release -notmatch 'docs-only') -Message "The release workflow stays full."
    Assert-True -Condition ($evidence -match '(?m)^    paths:\s*$') -Message "UI evidence keeps its existing path filter."
    Assert-True -Condition ($evidence -match '"frontend/\*\*"') -Message "UI evidence still triggers from frontend changes."
    Assert-True -Condition ($evidence -notmatch '"docs/') -Message "UI evidence must not be fabricated for documentation."
}

Write-Host "Docs-only workflow contract tests: $($script:Passed) passed, $($script:Failed) failed."
if ($script:Failed -ne 0) {
    exit 1
}
