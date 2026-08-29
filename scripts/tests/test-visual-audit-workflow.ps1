# Static contract tests for the CI synthetic visual-audit wiring.
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

Invoke-Case "CI has a pull-request visual-audit path filter" {
    Assert-True -Condition ($workflow -match '(?ms)^  visual-audit-paths:.*?^  visual-audit:') -Message "ci.yml must define the visual-audit path-filter job before the audit job."
    Assert-True -Condition ($workflow -match '(?m)^    if: github\.event_name == ''pull_request''\r?$') -Message "Path filtering must run for pull requests only."
    Assert-True -Condition ($workflow -match 'scripts/visual_audit_paths\.py --from-file') -Message "The path-filter job must use the deterministic classifier."
    Assert-True -Condition ($workflow -match '(?m)^      run: \$\{\{ steps\.filter\.outputs\.run \}\}\r?$') -Message "The path-filter result must be exposed as a job output."
}

Invoke-Case "backend and documentation-only pull requests skip the heavy job" {
    Assert-True -Condition ($workflow -match "github\.event_name == 'push' \|\| needs\.visual-audit-paths\.outputs\.run == 'true'") -Message "The heavy audit must run on main pushes or eligible pull requests only."
    Assert-True -Condition ($workflow -match 'needs: visual-audit-paths') -Message "The heavy audit must depend on the path-filter job."
}

Invoke-Case "main push and release gate execute the synthetic audit" {
    Assert-True -Condition ($workflow -match '(?m)^  push:\s*$') -Message "CI must retain a push trigger."
    Assert-True -Condition ($workflow -match '(?m)^    branches: \[main\]\s*$') -Message "The visual audit release path must include main pushes."
    Assert-True -Condition ($workflow -match 'npm run audit:visual') -Message "CI must invoke npm run audit:visual."
    Assert-True -Condition ($workflow -match 'npx playwright install --with-deps chromium') -Message "CI must install the pinned Playwright browser dependencies."
    Assert-True -Condition ($workflow -match '(?ms)^  release-safety:.*?test-visual-audit-workflow\.ps1') -Message "Release safety must verify the visual-audit workflow contract."
}

Invoke-Case "visual audit stays synthetic and local" {
    $visualJob = [regex]::Match($workflow, '(?ms)^  visual-audit:\s*.*?(?=^  [A-Za-z0-9-]+:\s*$)').Value
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace($visualJob)) -Message "Could not isolate the visual-audit job."
    Assert-True -Condition ($visualJob -notmatch 'continue-on-error') -Message "The visual-audit job must remain a blocking CI check."
    foreach ($forbidden in @(
        'npm run preview',
        '--live',
        'HERMES_FINANCE_DATABASE_PATH',
        'owner database',
        'production runtime',
        '\.env'
    )) {
        Assert-True -Condition ($visualJob -notmatch $forbidden) -Message "Visual-audit job contains forbidden runtime marker '$forbidden'."
    }
}

Write-Host "Visual audit workflow contract tests: $($script:Passed) passed, $($script:Failed) failed."
if ($script:Failed -ne 0) {
    exit 1
}
