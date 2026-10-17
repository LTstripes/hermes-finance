[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Manifest, [switch]$ExitAfterReady)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'recovery-runtime-safety.ps1')
. (Join-Path $PSScriptRoot 'recovery-bootstrap-safety.ps1')
# Reuse the accepted gated kill-on-close Job wrapper. Its child cannot start
# before assignment; abrupt outer-parent exit closes the Job and all descendants.
$bootstrapToken = $env:HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN
if (-not [HermesRecoveryBootstrapNative]::IsCurrentProcessOwned($bootstrapToken)) {
    try {
        $innerArguments = @('-Manifest', $Manifest)
        if ($ExitAfterReady) { $innerArguments += '-ExitAfterReady' }
        if (-not $ExitAfterReady) { Write-Host 'Starting isolated instrument UAT: http://127.0.0.1:18868 (maximum 8 hours).' }
        $owned = Invoke-HermesOwnedRecoveryBootstrap -BoundaryScript (Join-Path $PSScriptRoot 'recovery-bootstrap-boundary.ps1') -RecoveryScript $PSCommandPath -Arguments $innerArguments -TimeoutSeconds 28800
        Write-Host $owned.StandardOutput
        exit $owned.ExitCode
    } catch { Write-Host 'Instrument UAT failed closed.'; exit 1 }
}
$uatPort = 18868
$uatProcess = $null
$uatCreation = $null
$uatExecutable = $null
$exitCode = 1

function Assert-UatBootstrapPath([string]$Path) {
    # #832 root-first bootstrap: never probe a child of an unchecked alias/UNC.
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path.Substring(3).Contains(':') -or
        $Path.Contains('"') -or @($Path -split '[\\/]' | Where-Object { $_ -eq '..' }).Count) { throw 'unsafe bootstrap path' }
    if ([int]([IO.DriveInfo]::new([IO.Path]::GetPathRoot($Path))).DriveType -notin @(2,3,5,6)) { throw 'local drive required' }
    $parts = [Collections.Generic.List[string]]::new()
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        $parts.Add($current)
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
    $parts.Reverse()
    foreach ($part in $parts) {
        $item = Get-Item -LiteralPath $part -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'linked bootstrap path' }
    }
    $leaf = Get-Item -LiteralPath $Path -Force
    if ($leaf.PSIsContainer -or $leaf.LinkType -eq 'HardLink') { throw 'ordinary bootstrap file required' }
}

function Assert-UatProcessIdentity {
    $uatProcess.Refresh()
    if ($uatProcess.HasExited) { throw 'owned process stopped' }
    $row = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $uatProcess.Id)
    if ($null -eq $row -or $null -eq $row.CreationDate -or
        $row.CreationDate.ToUniversalTime().Ticks -ne $uatCreation -or
        $row.ExecutablePath -ine $uatExecutable) { throw 'owned process identity unavailable' }
}

try {
    foreach ($command in @('Get-CimInstance','Get-NetTCPConnection')) {
        if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) { throw 'process inspection unavailable' }
    }
    $checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $python = Join-Path $checkout 'backend\.venv\Scripts\python.exe'
    Assert-UatBootstrapPath $Manifest
    Assert-UatBootstrapPath $python
    $binding = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
    $token = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    # Python rechecks all physical/profile/prepared/schema bindings; no migrator.
    $savedPythonPath = $env:PYTHONPATH
    $savedPythonHome = $env:PYTHONHOME
    try {
        $env:PYTHONPATH = ''
        $env:PYTHONHOME = ''
        $null = & $python -m hermes_finance.instrument_uat --manifest $Manifest --readiness-token $token --check 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'validation failed' }
        if (@(Get-NetTCPConnection -LocalPort $uatPort -State Listen -ErrorAction SilentlyContinue).Count) { throw 'port occupied' }
        $uatProcess = Start-Process -FilePath $python -WorkingDirectory (Join-Path $checkout 'backend') -WindowStyle Hidden -PassThru -ArgumentList @(
            '-m','hermes_finance.instrument_uat','--manifest',('"'+$Manifest+'"'),'--readiness-token',$token)
        $rootRow = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $uatProcess.Id)
        if ($null -eq $rootRow -or $null -eq $rootRow.CreationDate -or [string]::IsNullOrWhiteSpace($rootRow.ExecutablePath)) { throw 'process identity unavailable' }
        $uatCreation = $rootRow.CreationDate.ToUniversalTime().Ticks
        $uatExecutable = $rootRow.ExecutablePath
    } finally {
        $env:PYTHONPATH = $savedPythonPath
        $env:PYTHONHOME = $savedPythonHome
    }
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        Assert-UatProcessIdentity
        $listeners = @(Get-NetTCPConnection -LocalPort $uatPort -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq '127.0.0.1') {
            $rows = @(Get-CimInstance Win32_Process)
            $listenerId = [int]$listeners[0].OwningProcess
            if (-not (Test-HermesProcessTreeContains -RootProcessId $uatProcess.Id -CandidateProcessId $listenerId -ProcessRows $rows)) { throw 'foreign listener' }
            try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$uatPort/api/health" -Headers @{'X-Hermes-Uat-Token'=$token} -TimeoutSec 2 } catch { Start-Sleep -Milliseconds 250; continue }
            $message = @('instrument_uat_scratch',$uatPort,$health.pid,$health.process_started_ns,$binding.checkout_sha,$binding.database_identity,$binding.snapshot_sha256) -join '|'
            $hmac = [Security.Cryptography.HMACSHA256]::new([Text.Encoding]::ASCII.GetBytes($token))
            try { $proof = -join ($hmac.ComputeHash([Text.Encoding]::ASCII.GetBytes($message)) | ForEach-Object { $_.ToString('x2') }) } finally { $hmac.Dispose() }
            $child = @($rows | Where-Object { $_.ProcessId -eq $listenerId })
            if ($health.mode -cne 'instrument_uat_scratch' -or $health.pid -ne $listenerId -or $health.binding -cne $proof -or
                $child.Count -ne 1 -or $null -eq $child[0].CreationDate -or [string]::IsNullOrWhiteSpace($child[0].ExecutablePath) -or
                $child[0].CreationDate.ToUniversalTime().Ticks -lt $uatCreation) { throw 'readiness identity mismatch' }
            $ready = $true
            break
        }
        if ($listeners.Count -gt 0) { throw 'ambiguous listener' }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw 'readiness timeout' }
    Write-Host "Instrument UAT is ready: http://127.0.0.1:$uatPort"
    if (-not $ExitAfterReady) {
        while ($true) { Assert-UatProcessIdentity; Start-Sleep -Seconds 1 }
    }
    $exitCode = 0
} catch {
    Write-Host 'Instrument UAT failed closed.'
} finally {
    if ($null -ne $uatProcess) {
        $uatProcess.Refresh()
        if (-not $uatProcess.HasExited) {
            try {
                Assert-UatProcessIdentity
                $killer = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\taskkill.exe') -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/PID',$uatProcess.Id,'/T','/F')
                if ($killer.ExitCode -ne 0) { throw 'cleanup failed' }
                $uatProcess.WaitForExit(5000) | Out-Null
            } catch { Write-Host 'Owned UAT cleanup could not be verified.'; $exitCode = 1 }
        }
    }
}
exit $exitCode
