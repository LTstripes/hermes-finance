# Static contract tests for the CI Windows launcher path gate.
# No network calls, runtime startup, credentials or private data.

[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$workflowPath = Join-Path $repoRoot ".github\workflows\ci.yml"
if (-not (Test-Path -LiteralPath $workflowPath -PathType Leaf)) {
    throw "CI workflow not found: $workflowPath"
}

$workflow = [IO.File]::ReadAllText($workflowPath)
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

Invoke-Case "workflow trigger is not path-filtered" {
    $onBlock = [regex]::Match($workflow, '(?ms)^on:\s*.*?(?=^permissions:\s*$)').Value
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace($onBlock)) -Message "Could not isolate the workflow trigger."
    Assert-True -Condition ($onBlock -match '(?m)^  push:\s*$') -Message "CI must retain a push trigger."
    Assert-True -Condition ($onBlock -match '(?m)^  pull_request:\s*$') -Message "CI must retain a pull_request trigger."
    Assert-True -Condition ($onBlock -notmatch 'paths-ignore') -Message "Workflow-level paths-ignore leaves a required check pending."
    Assert-True -Condition ($onBlock -notmatch '(?m)^\s*paths:') -Message "Workflow-level paths filters leave a required check pending. Gate the heavy job instead."
}

Invoke-Case "launcher path filter runs for pull requests and pushes" {
    $filterJob = [regex]::Match($workflow, '(?ms)^  windows-launcher-paths:\s*.*?(?=^  windows-launcher-safety:\s*$)').Value
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace($filterJob)) -Message "ci.yml must define windows-launcher-paths immediately before windows-launcher-safety."
    Assert-True -Condition ($filterJob -notmatch '(?m)^    if:') -Message "The launcher path filter must run on both pull_request and push."
    Assert-True -Condition ($filterJob -match 'scripts/launcher_ci_paths\.py --from-file') -Message "The path-filter job must use the deterministic classifier."
    Assert-True -Condition ($filterJob -match 'git diff --name-only --no-renames') -Message "The diff must list both sides of a rename so moving a launcher file out of the tree cannot skip the harness."
    Assert-True -Condition ($filterJob -match '0000000000000000000000000000000000000000') -Message "A push with no previous commit must be recognized."
    Assert-True -Condition ($filterJob -match 'run=true') -Message "An unresolvable push baseline must fail closed by running the harness."
    Assert-True -Condition ($filterJob -match 'github\.event\.pull_request\.base\.sha') -Message "Pull requests must diff against the base SHA."
    Assert-True -Condition ($filterJob -match 'github\.event\.before') -Message "Pushes must diff against github.event.before."
    Assert-True -Condition ($filterJob -match 'run: \$\{\{ steps\.filter\.outputs\.run \}\}') -Message "The path-filter result must be exposed as a job output."
}

Invoke-Case "heavy launcher job runs only after a positive classification" {
    $launcherJob = [regex]::Match($workflow, '(?ms)^  windows-launcher-safety:\s*.*\z').Value
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace($launcherJob)) -Message "Could not isolate the windows-launcher-safety job."
    Assert-True -Condition ($launcherJob -match 'needs: windows-launcher-paths') -Message "The heavy job must depend on the path filter."
    Assert-True -Condition ($launcherJob -match 'always\(\)') -Message "always() is required so a skipped dependency reports a terminal check instead of pending."
    Assert-True -Condition ($launcherJob -match '!cancelled\(\)') -Message "Cancellation must not start the heavy harness."
    Assert-True -Condition ($launcherJob -match "needs\.windows-launcher-paths\.result == 'success'") -Message "A failed path filter must not count as an irrelevant diff."
    Assert-True -Condition ($launcherJob -match "needs\.windows-launcher-paths\.outputs\.run == 'true'") -Message "The heavy harness must run only when the classifier returns true."
    Assert-True -Condition ($launcherJob -match 'test-windows-launcher-package\.ps1') -Message "The heavy job must keep the canonical package/install smoke."
    Assert-True -Condition ($launcherJob -match 'actions/setup-dotnet@v4') -Message "The .NET setup must stay inside the heavy job so irrelevant diffs do not start it."
    Assert-True -Condition ($launcherJob -notmatch 'continue-on-error') -Message "The launcher safety job must remain a blocking CI check."
    Assert-True -Condition ($workflow -match '(?ms)^  release-safety:.*?test-launcher-ci-workflow\.ps1') -Message "Release safety must verify the launcher workflow contract."
}

Write-Host "Launcher CI workflow contract tests: $($script:Passed) passed, $($script:Failed) failed."
if ($script:Failed -ne 0) {
    exit 1
}
