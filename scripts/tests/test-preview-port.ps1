[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
. (Join-Path $repo "scripts/prepare-preview-lib.ps1")
. (Join-Path $repo "scripts/recovery-runtime-safety.ps1")
. (Join-Path $repo "scripts/recovery-readiness.ps1")
$start = Join-Path $repo "scripts/start-local.ps1"
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($start, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw "Start parser failed: $parseErrors" }
foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:checks = 0
function Check([bool]$Value, [string]$Label) {
    if (-not $Value) { throw "Preview port assertion failed: $Label" }
    $script:checks++
}
function Reject([scriptblock]$Operation, [string]$Label) {
    $failed = $false
    try { & $Operation | Out-Null } catch { $failed = $true }
    Check $failed $Label
}

# No actual listener or child backend: synthetic filesystem/process/HTTP observations only.
$root = Join-Path ([IO.Path]::GetTempPath()) ("hermes-preview-port-" + [guid]::NewGuid().ToString("N"))
$checkout = Join-Path $root "Preview With Spaces"
$control = Join-Path $root "Control"
$stable = Join-Path $root "Stable"
$stableData = Join-Path $root "StableData"
$previewData = Join-Path $root "PreviewData"
foreach ($directory in @($checkout, $control, $stable, $stableData, $previewData, "$checkout/backend/.venv/Scripts", "$checkout/frontend", "$checkout/scripts", "$checkout/.git", "$stable/.git", "$control/.git")) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$stableDb = Join-Path $stableData "stable.db"
$previewDb = Join-Path $previewData "preview.db"
Set-Content -LiteralPath $stableDb -Value "synthetic Stable file, never SQLite-opened"
Set-Content -LiteralPath $previewDb -Value "synthetic Preview file, never SQLite-opened"
Set-Content -LiteralPath "$checkout/backend/.venv/Scripts/python.exe" -Value "synthetic interpreter marker, never executed"
Set-Content -LiteralPath "$previewData/.hermes-data-identity.json" -Value '{"kind":"preview"}'
$sha = "a" * 40
Set-Content -LiteralPath "$checkout/.hermes-runtime-prepared.json" -Value ('{"git_head":"' + $sha + '"}')
$pin = [ordered]@{ ControlCheckout=$control; StableCheckout=$stable; StableDataDirectory=$stableData; StableDatabase=$stableDb; PreviewCheckout=$checkout; PreviewDataDirectory=$previewData; PreviewDatabase=$previewDb; CandidateSha=$sha }
function Save-Pin {
    $pin.BoundarySha256 = Get-HermesPreviewBoundaryDigest -Boundary $pin
    $pin | ConvertTo-Json | Set-Content -LiteralPath "$checkout/.hermes-preview-boundary.json" -Encoding UTF8
}
Save-Pin
$script:configuredDatabase = $previewDb
$script:observedHead = $sha
$script:identityOutput = "b" * 64
# Replace the native boundary dependencies, never the admission functions being tested.
function Invoke-HermesPreviewNativeCommand {
    param($Request)
    $text = ""
    if ($Request.Name -eq "runtime-database") { $text = $script:configuredDatabase | ConvertTo-Json }
    elseif ($Request.Name -eq "preview-file-identity") { $text = $script:identityOutput }
    elseif ($Request.Name -eq "git") {
        $arguments = @($Request.Arguments)
        if ($arguments -contains "HEAD") { $text = $script:observedHead }
        elseif ($arguments -contains "--show-toplevel") { $text = $Request.WorkingDirectory }
        elseif ($arguments -contains "--git-common-dir" -or $arguments -contains "--git-dir") { $text = Join-Path $Request.WorkingDirectory ".git" }
    }
    return [pscustomobject]@{ ExitCode=0; Stdout=$text; Stderr="" }
}
Check ((Get-HermesStartPort -PreviewRequested $false -PreviewPort 18869) -eq 8000) "unselected/default port remains 8000"
Check ((Get-HermesStartPort -PreviewRequested $true -PreviewPort 18869) -eq 18869) "explicit Preview port"
foreach ($port in @(0, -1, 80, 8000, 65536)) { Reject { Get-HermesStartPort -PreviewRequested $true -PreviewPort $port } "invalid port $port" }
Reject { Get-HermesStartPort -PreviewRequested $true -PreviewPort 18869 -RecoveryReadiness $true } "recovery combination"
Reject { Get-HermesStartPort -PreviewRequested $true -PreviewPort 18869 -ScratchPreflight $true } "scratch combination"
Reject { Get-HermesStartPort -PreviewRequested $true -PreviewPort 18869 -ScratchManifest "synthetic" } "scratch manifest combination"
$binding = Get-HermesPreviewStartBinding -Checkout $checkout
Check ($binding.Database -eq $previewDb -and $binding.CheckoutSha -ceq $sha -and $binding.DatabaseIdentity -ceq ("b" * 64) -and $binding.Token -cmatch '^[0-9a-f]{64}$') "valid candidate / isolated file identity"
Check ((Get-HermesPreviewStartBinding -Checkout $checkout).Token -cne $binding.Token) "fresh per-start nonce"
Set-Content -LiteralPath "$checkout/.hermes-preview-boundary.json" -Value '{}'
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "missing/legacy candidate stamp"
Save-Pin
$pin.PreviewDatabase = $stableDb
$pin | ConvertTo-Json | Set-Content -LiteralPath "$checkout/.hermes-preview-boundary.json"
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "tampered boundary digest"
Save-Pin
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "rehashed production file still rejected"
$pin.PreviewDatabase = $previewDb; Save-Pin
Set-Content -LiteralPath "$previewData/.hermes-data-identity.json" -Value '{"kind":"production"}'
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "production sidecar"
Set-Content -LiteralPath "$previewData/.hermes-data-identity.json" -Value '{"kind":"preview"}'
$script:observedHead = "c" * 40
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "HEAD mismatch"
$script:observedHead = $sha
Set-Content -LiteralPath "$checkout/.hermes-runtime-prepared.json" -Value ('{"git_head":"' + ("c" * 40) + '"}')
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "prepared SHA mismatch"
Set-Content -LiteralPath "$checkout/.hermes-runtime-prepared.json" -Value ('{"git_head":"' + $sha + '"}')
$script:configuredDatabase = $stableDb
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "runtime configured DB mismatch"
$script:configuredDatabase = $previewDb
$script:identityOutput = "invalid"
Reject { Get-HermesPreviewStartBinding -Checkout $checkout } "unavailable file identity"
$script:identityOutput = "b" * 64

$process = [Diagnostics.Process]::GetCurrentProcess()
$created = $process.StartTime.ToUniversalTime()
$identity = [pscustomobject]@{ ProcessId=$process.Id; CreationTicks=$created.Ticks; ExecutablePath="synthetic-root.exe" }
$script:rows = @([pscustomobject]@{ ProcessId=$process.Id; ParentProcessId=0; CreationDate=$created; ExecutablePath="synthetic-root.exe" })
$script:listeners = @([pscustomobject]@{ State="Listen"; LocalPort=18869; LocalAddress="127.0.0.1"; OwningProcess=$process.Id })
function Get-NetTCPConnection { param($LocalPort, $State) return $script:listeners }
function Get-CimInstance { param($ClassName, $Filter) return $script:rows }
function Assert-ProcessRunning { param($Process, $Name) }
function Start-Sleep { param($Milliseconds) throw "Unexpected retry in deterministic readiness fixture" }
$script:requests = @()
$script:forged = ""
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    $script:requests += $Uri
    $headers = @{ "X-Hermes-Recovery-Token"=$binding.Token; "X-Hermes-Recovery-Database-Identity"=$binding.DatabaseIdentity; "X-Hermes-Recovery-Checkout-SHA"=$binding.CheckoutSha }
    if ($script:forged) { $headers[$script:forged] = "forged" }
    return [pscustomobject]@{ StatusCode=200; Content="Hermes Finance"; Headers=$headers }
}
Wait-ForPreviewStack -Backend $process -Identity $identity -Binding $binding -Port 18869
Check (($script:requests -join ',') -ceq "http://127.0.0.1:18869/api/health,http://127.0.0.1:18869/api/months,http://127.0.0.1:18869/") "selected port / three ordinary surfaces only"
foreach ($header in @("X-Hermes-Recovery-Token", "X-Hermes-Recovery-Database-Identity", "X-Hermes-Recovery-Checkout-SHA")) {
    $script:forged = $header
    Reject { Wait-ForPreviewStack -Backend $process -Identity $identity -Binding $binding -Port 18869 } "forged response $header"
}
$script:forged = ""
$script:listeners[0].OwningProcess = $process.Id + 10000
Reject { Wait-ForPreviewStack -Backend $process -Identity $identity -Binding $binding -Port 18869 } "foreign listener"
$script:listeners[0].OwningProcess = $process.Id
$script:listeners[0].LocalAddress = "0.0.0.0"
Reject { Wait-ForPreviewStack -Backend $process -Identity $identity -Binding $binding -Port 18869 } "wildcard listener"
$script:listeners[0].LocalAddress = "127.0.0.1"
$script:rows[0].CreationDate = $created.AddSeconds(1)
Reject { Wait-ForPreviewStack -Backend $process -Identity $identity -Binding $binding -Port 18869 } "reused root PID"
$script:rows[0].CreationDate = $created
$childId = $process.Id + 1
$child = [pscustomobject]@{ ProcessId=$childId; ParentProcessId=$process.Id; CreationDate=$created.AddSeconds(1); ExecutablePath="synthetic-child.exe" }
$script:rows += $child
$script:listeners[0].OwningProcess = $childId
Check (Test-HermesPreviewListenerOwnership -RootProcessId $process.Id -RootCreationTicks $created.Ticks -RootExecutablePath "synthetic-root.exe" -Port 18869 -Listeners $script:listeners -ProcessRows $script:rows) "current owned child accepted"
$child.CreationDate = $created.AddSeconds(-1)
Check (-not (Test-HermesPreviewListenerOwnership -RootProcessId $process.Id -RootCreationTicks $created.Ticks -RootExecutablePath "synthetic-root.exe" -Port 18869 -Listeners $script:listeners -ProcessRows $script:rows)) "stale child ancestry rejected"
Reject { Assert-PortAvailable -Port 18869 -RequireInspection $true } "occupied selected port, no process killed"
$script:listeners = @()
Assert-PortAvailable -Port 18869 -RequireInspection $true
Check $true "free selected port"

# Execute the stock main block in a fabricated checkout, replacing OS/native
# effects in this private test copy only. Admission/readiness were exercised above.
$injection = @'
function Get-RequiredCommand { param($Name, $InstallHint) return "synthetic-command.exe" }
function Invoke-PreparedRuntimeValidation { param($PowerShell, $Checkout) }
function Assert-PortAvailable { param($Port, $RecoveryReadiness, $RequireInspection) Set-Content -LiteralPath $env:HERMES_PREVIEW_TEST_LOG -Value ("port="+$Port+";strict="+$RequireInspection) }
function Get-HermesPreviewStartBinding { param($Checkout) return [pscustomobject]@{ Database=(Join-Path $Checkout "synthetic.db"); DatabaseIdentity=("b"*64); CheckoutSha=("a"*40); Token=("c"*64) } }
function Assert-HermesPreviewPinnedRuntimeBoundary { param($Checkout) return $null }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$NoNewWindow, [switch]$PassThru)
    Add-Content -LiteralPath $env:HERMES_PREVIEW_TEST_LOG -Value ("child="+$env:HERMES_FINANCE_PORT+";host="+$env:HERMES_FINANCE_HOST+";offline="+$env:UV_OFFLINE+";args="+($ArgumentList -join ','))
    if ($env:HERMES_FINANCE_PORT -eq "18869") {
        if ($env:HERMES_FINANCE_RECOVERY_READINESS_TOKEN -cne ("c"*64) -or $env:HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY -cne ("b"*64) -or $env:HERMES_FINANCE_RECOVERY_CHECKOUT_SHA -cne ("a"*40) -or $env:HERMES_FINANCE_DATABASE_PATH -ne (Join-Path (Split-Path $WorkingDirectory -Parent) "synthetic.db")) { throw "child binding not threaded" }
    }
    return [Diagnostics.Process]::GetCurrentProcess()
}
function Get-HermesPreviewProcessIdentity { param($Backend) return [pscustomobject]@{ ProcessId=$Backend.Id; CreationTicks=1; ExecutablePath="synthetic.exe" } }
function Wait-ForPreviewStack { param($Backend, $Identity, $Binding, $Port) if ($Port -ne 18869 -or $Binding.Token -cne ("c"*64)) { throw "readiness binding not threaded" } }
function Wait-ForProductionStack { param($Backend, $RequireRecoverySurfaces, $ExpectedRecoveryToken, $ExpectedDatabaseIdentity, $ExpectedCheckoutSha) }
function Stop-ProcessTree { param($Process, $Name) if ($null -ne $Process) { Add-Content -LiteralPath $env:HERMES_PREVIEW_TEST_LOG -Value "owned-cleanup" } }
'@
foreach ($name in @("prepare-preview-lib.ps1", "recovery-runtime-safety.ps1", "recovery-readiness.ps1")) { Copy-Item -LiteralPath (Join-Path $repo "scripts/$name") -Destination "$checkout/scripts/$name" }
Set-Content -LiteralPath "$checkout/backend/pyproject.toml" -Value "synthetic"
Set-Content -LiteralPath "$checkout/frontend/package.json" -Value '{}'
$source = (Get-Content -LiteralPath $start -Raw).Replace("`r`n", "`n")
$at = $source.IndexOf("try {`n    `$selectedPort = Get-HermesStartPort", [StringComparison]::Ordinal)
Check ($at -gt 0) "stock main block located"
[IO.File]::WriteAllText("$checkout/scripts/start-local.ps1", $source.Insert($at, $injection + "`n"), (New-Object Text.UTF8Encoding($true)))
$powerShell = Join-Path $env:SystemRoot "System32/WindowsPowerShell/v1.0/powershell.exe"
$savedLog = $env:HERMES_PREVIEW_TEST_LOG
$savedPort = $env:HERMES_FINANCE_PORT
$savedRecovery = @{}
try {
    foreach ($name in @("HERMES_FINANCE_RECOVERY_READINESS_TOKEN", "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY", "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA")) { $savedRecovery[$name] = [Environment]::GetEnvironmentVariable($name, "Process"); Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    $env:HERMES_FINANCE_PORT = "43210"
    foreach ($explicit in @($false, $true)) {
        $env:HERMES_PREVIEW_TEST_LOG = Join-Path $root ("launch-"+$explicit+".log")
        $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$checkout/scripts/start-local.ps1", "-ExitAfterReady")
        if ($explicit) { $arguments += @("-PreviewPort", "18869") }
        $output = & $powerShell @arguments 2>&1 | Out-String
        Check ($LASTEXITCODE -eq 0) "synthetic stock start: $output"
        $port = if ($explicit) { 18869 } else { 8000 }
        $log = Get-Content -LiteralPath $env:HERMES_PREVIEW_TEST_LOG -Raw
        Check ($output.Contains("http://127.0.0.1:$port")) "ready output uses selected port"
        Check ($log.Contains("child=$port;host=127.0.0.1;offline=1;args=run,--locked,--offline,--no-sync,hermes-finance-api")) "child port, loopback, locked offline/no-sync preserved"
        Check ($log.Contains("owned-cleanup")) "only launched root cleanup path retained"
    }
}
finally {
    $env:HERMES_PREVIEW_TEST_LOG = $savedLog
    $env:HERMES_FINANCE_PORT = $savedPort
    foreach ($name in $savedRecovery.Keys) { [Environment]::SetEnvironmentVariable($name, $savedRecovery[$name], "Process") }
}
# Retain only these fabricated artifacts; no recursive deletion or runtime stop.
Write-Output "Preview port synthetic admission/readiness/start regression: PASS ($script:checks checks)"
