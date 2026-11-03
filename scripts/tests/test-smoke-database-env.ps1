[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$script:checks = 0
function Check([bool]$Value, [string]$Label) {
    if (-not $Value) { throw "Smoke environment assertion failed: $Label" }
    $script:checks++
}
$root = Join-Path ([IO.Path]::GetTempPath()) ("hermes-smoke-env-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $root | Out-Null
$databasePath = Join-Path $root "synthetic.db"
Set-Content -LiteralPath $databasePath -Value "synthetic marker; never SQLite-opened"
$repoRoot = $root
$launcher = Join-Path $root "fake-launcher.ps1"
$listenPort = 8000
$expectedRevision = "synthetic-revision"
$originalDatabase = [Environment]::GetEnvironmentVariable("HERMES_FINANCE_DATABASE_PATH", "Process")
$originalToken = [Environment]::GetEnvironmentVariable("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", "Process")
$parentDatabase = $null
$parentToken = $null
function Check-SmokeDotenv {
    Check ([IO.File]::ReadAllText($envFile) -ceq "HERMES_FINANCE_DATABASE_PATH=$databasePath") "only synthetic database configured until launcher cleanup"
}
function Check-ParentEnvironment {
    Check ($env:HERMES_FINANCE_DATABASE_PATH -ceq $parentDatabase) "parent database restored before readiness/cleanup"
    Check ($env:HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN -ceq $parentToken) "parent token restored before readiness/cleanup"
}
# These replace every native/runtime boundary of the extracted stock main block.
# No original smoke functions, real launcher, HTTP, SQLite or process stop runs.
function Start-WindowsPowerShellFile {
    param($FilePath, $WorkingDirectory)
    $script:launchCalls++
    Check-SmokeDotenv
    Check ($env:HERMES_FINANCE_DATABASE_PATH -ceq $databasePath) "synthetic database override applies during child creation"
    Check ($null -eq $env:HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN) "child does not inherit token override"
    if ($mode -in @("launch-failure", "launch-and-cleanup-failure")) { throw "synthetic-launch-failure" }
    return [Diagnostics.Process]::GetCurrentProcess()
}
function Wait-ForProductionStack {
    param($Process)
    $script:waitCalls++
    Check-SmokeDotenv
    Check-ParentEnvironment
    if ($mode -eq "wait-failure") { throw "synthetic-wait-failure" }
    return [pscustomobject]@{ Content=('{"status":"ok","version":"' + $expectedVersion + '"}') }
}
function Get-AlembicRevision { param($DatabasePath) Check-ParentEnvironment; return $expectedRevision }
function Assert-ExactLoopbackListener { param($Port) Check-ParentEnvironment }
function Stop-ProcessTree {
    param($Process, $Name)
    $script:stopCalls++
    Check-SmokeDotenv
    Check-ParentEnvironment
    if ($mode -in @("cleanup-failure", "launch-and-cleanup-failure")) { throw "synthetic-cleanup-failure" }
}
try {
    foreach ($relative in @("scripts/r06-10-windows-smoke.ps1", "scripts/history/r05-11-windows-smoke.ps1", "scripts/history/r04-08-windows-smoke.ps1")) {
        $tokens = $null; $parseErrors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $relative), [ref]$tokens, [ref]$parseErrors)
        Check ($parseErrors.Count -eq 0) "smoke parses: $relative"
        $main = @($ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.TryStatementAst] -and $_.Body.Extent.Text.Contains('Start-WindowsPowerShellFile') })
        Check ($main.Count -eq 1) "one stock launch/cleanup block: $relative"
        $operation = [scriptblock]::Create($main[0].Extent.Text)
        $expectedVersion = if ($relative.Contains("r06-10")) { "0.7.0" } else { "0.5.0" }
        foreach ($present in @($false, $true)) {
            $parentDatabase = if ($present) { Join-Path $root "parent-synthetic.db" } else { $null }
            $parentToken = if ($present) { "synthetic-token-sentinel" } else { $null }
            foreach ($dotenvState in @("missing", "empty", "populated")) {
                foreach ($mode in @("success", "launch-failure", "wait-failure", "cleanup-failure", "launch-and-cleanup-failure")) {
                    [Environment]::SetEnvironmentVariable("HERMES_FINANCE_DATABASE_PATH", $parentDatabase, "Process")
                    [Environment]::SetEnvironmentVariable("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", $parentToken, "Process")
                    # Use the same saved values as the script setup, without reading
                    # any runtime .env or executing the smoke script's top level.
                    $savedDatabase = [Environment]::GetEnvironmentVariable("HERMES_FINANCE_DATABASE_PATH", "Process")
                    $savedToken = [Environment]::GetEnvironmentVariable("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", "Process")
                    $envFile = Join-Path $repoRoot ".env"
                    $envExisted = $dotenvState -ne "missing"
                    $savedEnv = [byte[]]@()
                    if ($dotenvState -eq "populated") { $savedEnv = [Text.Encoding]::UTF8.GetBytes("# synthetic sentinel`r`nUNRELATED=synthetic-token-sentinel`r`nHERMES_FINANCE_DATABASE_PATH=parent.db") }
                    if ($envExisted) { [IO.File]::WriteAllBytes($envFile, $savedEnv) }
                    $launcherProcess = $null
                    $script:launchCalls = 0; $script:waitCalls = 0; $script:stopCalls = 0
                    $failure = $null
                    try { & $operation 6>$null | Out-Null }
                    catch { $failure = $_.Exception.Message }
                    if ($mode -eq "success") { Check ($null -eq $failure) "synthetic success: $relative" }
                    else {
                        $expectedFailure = if ($mode.Contains("cleanup")) { "synthetic-cleanup-failure" } elseif ($mode -eq "launch-failure") { "synthetic-launch-failure" } else { "synthetic-wait-failure" }
                        Check ($failure -ceq $expectedFailure) "expected injected failure: $relative / $mode"
                    }
                    Check ($script:launchCalls -eq 1 -and $script:stopCalls -eq 1) "launch and cleanup invoked exactly once"
                    Check ($script:waitCalls -eq $(if ($mode -in @("launch-failure", "launch-and-cleanup-failure")) { 0 } else { 1 })) "readiness only after successful child creation"
                    Check-ParentEnvironment
                    Check ((Test-Path -LiteralPath $envFile) -eq $envExisted) "original dotenv presence restored: $dotenvState / $mode"
                    if ($envExisted) {
                        Check ([Convert]::ToBase64String([IO.File]::ReadAllBytes($envFile)) -ceq [Convert]::ToBase64String($savedEnv)) "original dotenv bytes restored: $dotenvState / $mode"
                        Remove-Item -LiteralPath $envFile
                    }
                }
            }
        }
    }
}
finally {
    [Environment]::SetEnvironmentVariable("HERMES_FINANCE_DATABASE_PATH", $originalDatabase, "Process")
    [Environment]::SetEnvironmentVariable("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", $originalToken, "Process")
}
Write-Output "Smoke database environment synthetic regression: PASS ($script:checks checks)"
