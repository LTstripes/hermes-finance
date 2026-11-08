<#
.SYNOPSIS
    Guide the Owner through an explicit backup-first OPS02 and optional Start.
.DESCRIPTION
    Run from canonical Main. DryRun performs local reads only (no Git fetch/pull,
    prompts, backup, update or Start). Only a literal absolute database selector
    is accepted from Stable/.env; interpolation and duplicate selectors refuse.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TargetVersion,
    [string]$StableCheckout,
    [switch]$DryRun
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Invoke-HermesGuidedGit {
    param([string]$Main, [string[]]$Arguments)
    # Windows PowerShell 5.1 turns redirected native stderr (for example the
    # "From https://..." progress of git pull) into a terminating error under
    # Stop. Only the exit code decides success; stderr is discarded unread.
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & git --no-optional-locks -C $Main @Arguments 2>$null | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "Main Git operation failed; no automatic recovery is attempted." }
    return $output.Trim()
}

function Assert-HermesGuidedMain {
    param([string]$Main)
    if ((Split-Path $Main -Leaf) -ine "main" -or
        [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\', '/') -ine $Main) {
        throw "Run this script from the trusted canonical Main checkout."
    }
    $top = Invoke-HermesGuidedGit $Main @("rev-parse", "--show-toplevel")
    if ([IO.Path]::GetFullPath($top).TrimEnd('\', '/') -ine $Main -or
        (Invoke-HermesGuidedGit $Main @("branch", "--show-current")) -cne "main") {
        throw "Canonical Main root and main branch are required."
    }
    $origin = Invoke-HermesGuidedGit $Main @("remote", "get-url", "--all", "origin")
    if ($origin -cnotmatch '^(https://github\.com/LTstripes/hermes-finance(?:\.git)?|git@github\.com:LTstripes/hermes-finance(?:\.git)?)$') {
        throw "Main must use the canonical Hermes origin."
    }
    if (Invoke-HermesGuidedGit $Main @("status", "--porcelain=v1", "--untracked-files=all")) {
        throw "Main is dirty; commit or remove development changes separately."
    }
    # Refuse local-only commits, even if pull --ff-only would leave them intact.
    $head = Invoke-HermesGuidedGit $Main @("rev-parse", "--verify", "HEAD")
    $base = Invoke-HermesGuidedGit $Main @("merge-base", "HEAD", "refs/remotes/origin/main")
    if ($head -cne $base) { throw "Main has local or divergent commits; guided update is blocked." }
}

function Get-HermesGuidedDatabase {
    param([string]$Stable)
    $file = Join-Path $Stable ".env"
    $selectors = New-Object 'System.Collections.Generic.List[string]'
    try {
        # Never load dotenv into the process environment or evaluate its values.
        foreach ($line in [IO.File]::ReadLines($file)) {
            if ($line -match '^\s*(?:export\s+)?HERMES_FINANCE_DATABASE_PATH\s*=\s*(.*)$') {
                $selectors.Add($Matches[1])
            }
        }
    }
    catch { throw "Cannot read Stable database selector." }
    if ($selectors.Count -ne 1) { throw "Stable requires exactly one database selector." }
    $value = $selectors[0].Trim()
    if ($value -match "^'([^']*)'\s*(?:#.*)?$") { $value = $Matches[1] }
    elseif ($value -match '^"([^"\r\n]*)"\s*(?:#.*)?$') {
        $value = $Matches[1]
        if ($value.Contains('\')) { throw 'Use forward slashes in a double-quoted database selector to avoid dotenv escape ambiguity.' }
    }
    else { $value = ($value -replace '\s+#.*$', '').Trim() }
    # A deliberately narrow literal format avoids dotenv interpolation/escaping
    # ambiguity. Refuse without echoing malformed input or other dotenv content.
    if ($value -notmatch '^[A-Za-z]:[\\/]' -or $value -match '[\x00-\x1f\x7f$`"''%]' -or $value.Substring(3).Contains(':')) {
        throw "Stable database selector must be a literal absolute local file path."
    }
    try {
        $path = [IO.Path]::GetFullPath($value)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "missing" }
        return $path
    }
    catch { throw "Stable database selector must resolve to an existing file." }
}

function Get-HermesGuidedListeners {
    return [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
}

function Assert-HermesGuidedPortFree {
    try { $listeners = @(Get-HermesGuidedListeners) }
    catch { throw "Cannot inspect runtime port 8000; update is blocked." }
    if (@($listeners | Where-Object { $_.Port -eq 8000 }).Count) {
        throw "Port 8000 is occupied; stop the owned runtime before updating."
    }
}

function Get-HermesGuidedPlan {
    param([string]$Main, [string]$Stable, [string]$Version)
    if ($Version -cnotmatch '^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') { throw "TargetVersion must be X.Y.Z or vX.Y.Z." }
    $versionNumber = $Version -replace '^v', ''
    if ([string]::IsNullOrWhiteSpace($Stable)) { $Stable = Join-Path (Split-Path $Main -Parent) "stable" }
    $Stable = [IO.Path]::GetFullPath($Stable)
    if ($Stable.TrimEnd('\', '/') -ieq $Main) { throw "Stable and Main must be separate checkouts." }
    $database = Get-HermesGuidedDatabase $Stable
    $backup = Join-Path (Split-Path $Main -Parent) "Backups\stable-$versionNumber-update"
    if (Test-Path -LiteralPath $backup) { throw "Proposed backup directory already exists; refusing reuse." }
    return [pscustomobject]@{ Main=$Main; Stable=$Stable; Version=$versionNumber; Database=$database; Backup=$backup }
}

function Format-HermesGuidedCommand {
    param($Plan)
    $values = @((Join-Path $Plan.Main 'scripts\update-stable.ps1'), $Plan.Stable, $Plan.Version, $Plan.Database, $Plan.Backup, $Plan.Main) |
        ForEach-Object { "'" + $_.Replace("'", "''") + "'" }
    return "& $($values[0]) -StableCheckout $($values[1]) -TargetVersion $($values[2]) -DatabasePath $($values[3]) -BackupDirectory $($values[4]) -ControlCheckout $($values[5])"
}

function Invoke-HermesGuidedUpdate {
    param($Plan)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Plan.Main 'scripts\update-stable.ps1') `
        -StableCheckout $Plan.Stable -TargetVersion $Plan.Version -DatabasePath $Plan.Database `
        -BackupDirectory $Plan.Backup -ControlCheckout $Plan.Main
    if ($LASTEXITCODE -ne 0) { throw "OPS02 failed; Start was not offered. Inspect the existing operation receipt before retrying." }
}

function Start-HermesGuidedStable {
    param($Plan)
    Assert-HermesGuidedPortFree
    $start = Join-Path $Plan.Stable 'scripts\start-local.ps1'
    if ($start.Contains('"')) { throw "Invalid Stable script path." }
    $process = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $start + '"')) `
        -WorkingDirectory $Plan.Stable -WindowStyle Normal -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($process.HasExited) { throw "Stable Start exited before health readback." }
        $health = $null
        try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 }
        catch { }
        if ($null -ne $health) {
            if ([string]$health.version -cne $Plan.Version) { throw "Stable health version differs from the requested release." }
            Write-Host "Stable /api/health version: $($Plan.Version)"
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Stable health readback timed out; inspect runtime state before retrying."
}

function Invoke-HermesGuidedOperation {
    param([string]$Main, [string]$Stable, [string]$Version, [switch]$DryRun)
    Assert-HermesGuidedMain $Main
    Assert-HermesGuidedPortFree
    $plan = Get-HermesGuidedPlan $Main $Stable $Version
    if (-not $DryRun) {
        Write-Host "Main synchronization: git pull --ff-only origin main"
        if ((Read-Host 'Type PULL to confirm fetching and fast-forwarding Main') -cne 'PULL') { throw "Main synchronization cancelled." }
        $null = Invoke-HermesGuidedGit $Main @('pull', '--ff-only', 'origin', 'main')
        Assert-HermesGuidedMain $Main
        $plan = Get-HermesGuidedPlan $Main $Stable $Version
    }
    Write-Host (Format-HermesGuidedCommand $plan)
    if ($DryRun) { return }
    if ((Read-Host "Verify the proposed accepted production database and backup path; type $($plan.Version) to authorize OPS02") -cne $plan.Version) { throw "Stable update cancelled." }
    Assert-HermesGuidedMain $Main
    Assert-HermesGuidedPortFree
    $freshPlan = Get-HermesGuidedPlan $Main $Stable $Version
    if ($freshPlan.Database -cne $plan.Database) { throw "Database selector changed after confirmation; update blocked." }
    Invoke-HermesGuidedUpdate $plan
    if ((Read-Host 'Type START to authorize the separate Stable Start') -ceq 'START') { Start-HermesGuidedStable $plan }
}

try {
    $main = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
    Invoke-HermesGuidedOperation -Main $main -Stable $StableCheckout -Version $TargetVersion -DryRun:$DryRun
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

