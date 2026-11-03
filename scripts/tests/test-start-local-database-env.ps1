[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$start = Join-Path $repo "scripts/start-local.ps1"
$python = Join-Path $repo "backend/.venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Tests require the existing prepared backend interpreter; no dependencies are installed." }
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($start, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw "Start parser failed" }
foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:checks = 0
function Check([bool]$Value, [string]$Label) {
    if (-not $Value) { throw "Database environment assertion failed: $Label" }
    $script:checks++
}
function Reject-Override([string]$Label, [string]$Interpreter = $python) {
    $failed = $false
    try { Clear-HermesUnpinnedDatabaseOverride -Checkout $checkout -Python $Interpreter }
    catch {
        $failed = $true
        Check ($_.Exception.Message.StartsWith("Inherited HERMES_FINANCE_DATABASE_PATH conflicts")) "$Label uses fixed diagnostic"
        Check (-not $_.Exception.Message.Contains($inherited)) "$Label does not expose the inherited path"
        Check (-not $_.Exception.Message.Contains("synthetic-private-value")) "$Label does not expose dotenv values"
    }
    Check $failed $Label
    Check ($env:HERMES_FINANCE_DATABASE_PATH -ceq $inherited) "$Label preserves caller on rejection"
}
$root = Join-Path ([IO.Path]::GetTempPath()) ("hermes-database-env-" + [guid]::NewGuid().ToString("N"))
$checkout = Join-Path $root "Checkout With Spaces"
foreach ($directory in @("$checkout/scripts", "$checkout/backend", "$checkout/frontend")) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
$envFile = Join-Path $checkout ".env"
$database = Join-Path $root "Synthetic Data/finance.db"
$inherited = $database
$encoding = New-Object Text.UTF8Encoding($true)
$names = @("HERMES_FINANCE_DATABASE_PATH", "HERMES_SYNTHETIC_DATABASE_ROOT", "HERMES_DATABASE_TEST_MODE", "HERMES_DATABASE_TEST_LOG", "HERMES_DATABASE_TEST_PYTHON", "HERMES_DATABASE_TEST_EXPECTED", "HERMES_FINANCE_RECOVERY_READINESS_TOKEN", "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY", "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA")
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
try {
    Remove-Item Env:HERMES_FINANCE_DATABASE_PATH -ErrorAction SilentlyContinue
    Clear-HermesUnpinnedDatabaseOverride -Checkout $checkout -Python "missing-interpreter"
    Check ($null -eq $env:HERMES_FINANCE_DATABASE_PATH) "no inherited override needs no interpreter or dotenv"
    $forward = $database.Replace('\', '/')
    $env:HERMES_SYNTHETIC_DATABASE_ROOT = Split-Path $database -Parent
    $examples = @(
        "HERMES_FINANCE_DATABASE_PATH=$database",
        "HERMES_FINANCE_DATABASE_PATH='$database' # comment",
        ('export hermes_finance_database_path="' + $forward + '" # comment'),
        ("HERMES_FINANCE_DATABASE_PATH=other.db" + [Environment]::NewLine + "HERMES_FINANCE_DATABASE_PATH='$database'"),
        ('HERMES_FINANCE_DATABASE_PATH=$' + '{HERMES_SYNTHETIC_DATABASE_ROOT}/finance.db')
    )
    foreach ($content in $examples) {
        [IO.File]::WriteAllText($envFile, $content, $encoding)
        $env:HERMES_FINANCE_DATABASE_PATH = $inherited
        Clear-HermesUnpinnedDatabaseOverride -Checkout $checkout -Python $python
        Check ($null -eq $env:HERMES_FINANCE_DATABASE_PATH) "equal dotenv override cleared (BOM/quotes/export/duplicates/interpolation)"
        $child = & $python -I -c "import os; print('clear' if 'HERMES_FINANCE_DATABASE_PATH' not in os.environ else 'leaked')"
        Check ($LASTEXITCODE -eq 0 -and $child -ceq "clear") "child receives no override"
    }
    [IO.File]::WriteAllText($envFile, "HERMES_FINANCE_DATABASE_PATH='../Synthetic Data/finance.db'", $encoding)
    Push-Location "$checkout/backend"
    try {
        $inherited = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path "../Synthetic Data/finance.db"))
        $env:HERMES_FINANCE_DATABASE_PATH = $inherited
        Clear-HermesUnpinnedDatabaseOverride -Checkout $checkout -Python $python
        Check ($null -eq $env:HERMES_FINANCE_DATABASE_PATH) "relative and absolute paths compare from backend cwd"
    }
    finally { Pop-Location }
    $inherited = $database
    $env:HERMES_FINANCE_DATABASE_PATH = $inherited
    foreach ($content in @("HERMES_FINANCE_DATABASE_PATH=other.db", "UNRELATED=synthetic-private-value", "HERMES_FINANCE_DATABASE_PATH", 'HERMES_FINANCE_DATABASE_PATH="unterminated')) {
        [IO.File]::WriteAllText($envFile, $content, $encoding)
        Reject-Override "different/missing/invalid dotenv setting refuses"
    }
    Remove-Item -LiteralPath $envFile
    Reject-Override "missing dotenv refuses instead of falling back to the default database"
    [IO.File]::WriteAllText($envFile, "HERMES_FINANCE_DATABASE_PATH='$database'", $encoding)
    Reject-Override "unavailable parser refuses" -Interpreter "$checkout/missing-python.exe"

    # Exercise the stock main block in a private synthetic copy. Only the native
    # boundaries are replaced; the real guard parses the fake dotenv above.
    $injection = @'
$realDatabaseGuard = (Get-Item function:Clear-HermesUnpinnedDatabaseOverride).ScriptBlock
function Clear-HermesUnpinnedDatabaseOverride {
    param($Checkout)
    Add-Content -LiteralPath $env:HERMES_DATABASE_TEST_LOG -Value "guard"
    & $realDatabaseGuard -Checkout $Checkout -Python $env:HERMES_DATABASE_TEST_PYTHON
}
function Get-RequiredCommand { param($Name, $InstallHint) return "synthetic-command.exe" }
function Invoke-PreparedRuntimeValidation { param($PowerShell, $Checkout) }
function Assert-PortAvailable { param($Port, $RecoveryReadiness, $RequireInspection) }
function Get-HermesPreviewStartBinding { param($Checkout) return [pscustomobject]@{ Database=$env:HERMES_DATABASE_TEST_EXPECTED; Token=("a"*64); DatabaseIdentity=("b"*64); CheckoutSha=("c"*40) } }
function Assert-HermesPreviewPinnedRuntimeBoundary { param($Checkout) if ($env:HERMES_DATABASE_TEST_MODE -eq "pinned") { return $env:HERMES_DATABASE_TEST_EXPECTED }; return $null }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$NoNewWindow, [switch]$PassThru)
    if ($env:HERMES_DATABASE_TEST_MODE -in @("preview", "pinned")) {
        if ($env:HERMES_FINANCE_DATABASE_PATH -cne $env:HERMES_DATABASE_TEST_EXPECTED) { throw "Wrong pinned child environment" }
    }
    elseif ($null -ne $env:HERMES_FINANCE_DATABASE_PATH) { throw "Child override was not cleared" }
    Add-Content -LiteralPath $env:HERMES_DATABASE_TEST_LOG -Value "spawn"
    if ($env:HERMES_DATABASE_TEST_MODE -eq "launch-failure") { throw "Synthetic launch failure" }
    return [Diagnostics.Process]::GetCurrentProcess()
}
function Get-HermesPreviewProcessIdentity { param($Backend) return [pscustomobject]@{ ProcessId=$Backend.Id } }
function Wait-ForPreviewStack { param($Backend, $Identity, $Binding, $Port) }
function Wait-ForProductionStack { param($Backend, $RequireRecoverySurfaces, $ExpectedRecoveryToken, $ExpectedDatabaseIdentity, $ExpectedCheckoutSha) }
function Stop-ProcessTree { param($Process, $Name) }
'@
    foreach ($name in @("prepare-preview-lib.ps1", "recovery-runtime-safety.ps1", "recovery-readiness.ps1")) { Copy-Item -LiteralPath (Join-Path $repo "scripts/$name") -Destination "$checkout/scripts/$name" }
    Set-Content -LiteralPath "$checkout/backend/pyproject.toml" -Value "synthetic"
    Set-Content -LiteralPath "$checkout/frontend/package.json" -Value '{}'
    $source = (Get-Content -LiteralPath $start -Raw).Replace(([string][char]13), '')
    $at = $source.IndexOf(('try {' + [char]10 + '    $selectedPort = Get-HermesStartPort'), [StringComparison]::Ordinal)
    Check ($at -gt 0) "stock main located"
    $source = $source.Insert($at, $injection + [char]10)
    $source = $source.Replace('exit $exitCode', @'
if ($env:HERMES_FINANCE_DATABASE_PATH -cne $env:HERMES_DATABASE_TEST_EXPECTED) { throw "Caller environment was not restored" }
Add-Content -LiteralPath $env:HERMES_DATABASE_TEST_LOG -Value "restored"
exit $exitCode
'@)
    [IO.File]::WriteAllText("$checkout/scripts/start-local.ps1", $source, $encoding)
    $powerShell = Join-Path $env:SystemRoot "System32/WindowsPowerShell/v1.0/powershell.exe"
    $env:HERMES_DATABASE_TEST_PYTHON = $python
    $env:HERMES_DATABASE_TEST_EXPECTED = $database
    foreach ($name in @("HERMES_FINANCE_RECOVERY_READINESS_TOKEN", "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY", "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA")) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    foreach ($mode in @("equal", "relative", "different", "missing", "launch-failure", "pinned", "preview")) {
        $env:HERMES_DATABASE_TEST_MODE = $mode
        $env:HERMES_DATABASE_TEST_LOG = Join-Path $root "$mode.log"
        $env:HERMES_FINANCE_DATABASE_PATH = $database
        $content = if ($mode -eq "relative") { "HERMES_FINANCE_DATABASE_PATH='../../Synthetic Data/finance.db'" } elseif ($mode -eq "different") { "HERMES_FINANCE_DATABASE_PATH=other.db" } elseif ($mode -eq "missing") { "UNRELATED=synthetic-private-value" } else { "HERMES_FINANCE_DATABASE_PATH='$database'" }
        [IO.File]::WriteAllText($envFile, $content, $encoding)
        $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$checkout/scripts/start-local.ps1", "-ExitAfterReady")
        if ($mode -eq "preview") { $arguments += @("-PreviewPort", "18869") }
        $output = & $powerShell @arguments 2>&1 | Out-String
        $expectedCode = if ($mode -in @("different", "missing", "launch-failure")) { 1 } else { 0 }
        Check ($LASTEXITCODE -eq $expectedCode) "stock main expected exit: $mode"
        $log = @(Get-Content -LiteralPath $env:HERMES_DATABASE_TEST_LOG)
        Check ($log -contains "restored") "stock main caller restored: $mode"
        Check (($log -contains "spawn") -eq ($mode -notin @("different", "missing"))) "refusal before process creation: $mode"
        Check (($log -contains "guard") -eq ($mode -notin @("preview", "pinned"))) "pinned starts preserve existing admission: $mode"
        Check (-not $output.Contains($database) -and -not $output.Contains("synthetic-private-value")) "stock output contains no paths or dotenv values: $mode"
    }
}
finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process") }
}
# Only synthetic temporary files are retained; no DB/listener/runtime was opened.
Write-Output "Start database environment synthetic regression: PASS ($script:checks checks)"
