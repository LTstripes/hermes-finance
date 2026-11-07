# Fully mocked git/gh request submission; never invokes native tools.
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "../release-lib.ps1")
. (Join-Path $PSScriptRoot "../release-request-lib.ps1")
$script:sha = "0123456789abcdef0123456789abcdef01234567"
$script:passed = 0
function Assert($value, $message) { if (-not $value) { throw $message } }
function Run-Case($name, $action) {
    $script:mode = ""
    $script:posts = 0
    $script:lists = 0
    $script:tempBody = ""
    $script:tempPath = ""
    & $action
    $script:passed++
    Write-Host "PASS: $name"
}
$runner = {
    param($request)
    $a = @($request.Arguments)
    $text = $a -join " "
    if ($text -match "remote get-url") {
        $out = if ($script:mode -eq "origin") { "https://github.com/other/repo" } else { "https://github.com/LTstripes/hermes-finance.git" }
    }
    elseif ($text -match "ls-remote") {
        $out = "$script:sha refs/heads/main"
        if ($script:mode -eq "sha") { $out = "bad refs/heads/main" }
    }
    elseif ($text -match "^run list") {
        Assert ($text -match "--workflow ci.yml") "Canonical workflow filter missing"
        $run = @{ headSha=$script:sha; event="push"; headBranch="main"; status="completed"; conclusion="success" }
        switch ($script:mode) {
            "ci-sha" { $run.headSha = "f" * 40 }
            "ci-event" { $run.event = "pull_request" }
            "ci-branch" { $run.headBranch = "other" }
            "ci-pending" { $run.status = "in_progress" }
            "ci-failed" { $run.conclusion = "failure" }
        }
        $out = ConvertTo-Json -InputObject @($run) -Compress
    }
    elseif ($text -match "/contents/") {
        Assert ($text.Contains("?ref=$script:sha")) "Notes are not pinned"
        if ($script:mode -eq "notes") { return New-HermesCommandResult -ExitCode 1 -Stdout "" -Stderr "not found" }
        $out = '{"type":"file","size":100}'
        if ($script:mode -eq "empty") { $out = '{"type":"file","size":0}' }
    }
    elseif ($text -eq "api user --jq .login") {
        $out = if ($script:mode -eq "user") { "other" } else { "LTstripes" }
    }
    elseif ($text -match "^issue comment") {
        $script:posts++
        Assert ($a[0] -eq "issue" -and $a[1] -eq "comment" -and $a[2] -eq "124") "Wrong control endpoint"
        Assert ($a -notcontains "--body") "Body argument forbidden"
        Assert ($a -notcontains "/release") "Trigger argument forbidden"
        $script:tempPath = $a[[Array]::IndexOf($a, "--body-file") + 1]
        $script:tempBody = [IO.File]::ReadAllText($script:tempPath)
        Assert (-not ([IO.File]::ReadAllBytes($script:tempPath)[0] -eq 239)) "Unexpected BOM"
        if ($script:mode -eq "post-fail") { return New-HermesCommandResult -ExitCode 1 -Stdout "" -Stderr "lost ACK" }
        $out = "https://github.com/LTstripes/hermes-finance/issues/124#issuecomment-123"
    }
    elseif ($text -match "/actions/runs/2/jobs") {
        $conclusion = if ($script:mode -eq "skipped") { "skipped" } else { $null }
        $out = @{jobs=@(@{name="Guarded release"; conclusion=$conclusion})} | ConvertTo-Json -Depth 5 -Compress
    }
    elseif ($text -match "/actions/workflows/release.yml/runs") {
        $script:lists++
        $runs = @()
        if ($script:lists -gt 1 -and $script:mode -ne "timeout") {
            $runs = @(@{id=2; event="issue_comment"; head_sha=$script:sha; actor=@{login="LTstripes"}; created_at=[DateTimeOffset]::UtcNow.ToString("o"); html_url="https://github.com/LTstripes/hermes-finance/actions/runs/2"})
            if ($script:mode -eq "ambiguous") { $runs += $runs[0].Clone(); $runs[1].id=3 }
        }
        $out = @{workflow_runs=$runs} | ConvertTo-Json -Depth 5 -Compress
    }
    else { throw "Unexpected command: $text" }
    return New-HermesCommandResult -ExitCode 0 -Stdout $out -Stderr ""
}
function Submit([switch]$DryRun, [string]$Version="9.8.7") {
    Submit-HermesReleaseRequest -Version $Version -RepoRoot $PSScriptRoot -CommandRunner $runner -CommandResolver { param($name) $name } -PollAttempts 2 -PollWait {} -DryRun:$DryRun
}
function Expect-Failure($action) {
    $failed = $false
    try { & $action } catch { $failed = $true }
    Assert $failed "Expected refusal"
}
Run-Case "dry run checks without mutation" {
    $body = Submit -DryRun
    Assert ($body -ceq "/release`nversion=9.8.7`nexpected_main_sha=$script:sha") "Wrong body"
    Assert ($script:posts -eq 0 -and $script:lists -eq 0) "Dry run posted or polled"
}
Run-Case "post exact file body and discover run" {
    Submit
    Assert ($script:tempBody -ceq "/release`nversion=9.8.7`nexpected_main_sha=$script:sha") "File body differs"
    Assert ($script:posts -eq 1) "Expected exactly one post"
    Assert (-not (Test-Path -LiteralPath $script:tempPath)) "Temporary file leaked"
}
foreach ($scenario in @("origin","sha","ci-sha","ci-event","ci-branch","ci-pending","ci-failed","notes","empty","user")) {
    Run-Case "refuse $scenario before posting" {
        $script:mode = $scenario
        Expect-Failure { Submit }
        Assert ($script:posts -eq 0) "Posted despite failed precheck"
    }
}
Run-Case "bad version" { Expect-Failure { Submit -Version "v1.2.3" }; Assert ($script:posts -eq 0) "Posted" }
foreach ($scenario in @("timeout","ambiguous","post-fail","skipped")) {
    Run-Case "$scenario never reposts and cleans temp" {
        $script:mode = $scenario
        Expect-Failure { Submit }
        Assert ($script:posts -eq 1) "Mutation retried"
        Assert (-not (Test-Path -LiteralPath $script:tempPath)) "Temporary file leaked"
    }
}
Write-Host "$script:passed passed"
