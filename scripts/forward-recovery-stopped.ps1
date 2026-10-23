[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RuntimeConfig,
    [Parameter(Mandatory=$true)][int]$RecoveryPid
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
try {
    $inventory = Get-Content -LiteralPath $RuntimeConfig -Raw | ConvertFrom-Json
    $stable = [IO.Path]::GetFullPath($inventory.canonical_production.checkout)
    $others = @($inventory.profiles | Where-Object { $_.type -ne 'stable' } | ForEach-Object {
        [IO.Path]::GetFullPath($_.checkout)
    })
    foreach ($process in @(Get-CimInstance Win32_Process)) {
        if ($process.ProcessId -eq $RecoveryPid) { continue }
        if ($process.Name -notmatch '^(python(w)?|uv|uvicorn|hermes-finance-api|powershell|pwsh|cmd)(\.exe)?$') { continue }
        $line = [string]$process.CommandLine
        if ([string]::IsNullOrWhiteSpace($line)) { throw 'process visibility unknown' }
        if ($line.IndexOf($stable, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw 'Stable process present'
        }
        if ($line -match 'hermes-finance-api|hermes_finance\.cli|uvicorn|start-local\.ps1') {
            $identifiedOther = $false
            foreach ($other in $others) {
                if ($line.IndexOf($other, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $identifiedOther = $true
                }
            }
            if (-not $identifiedOther) { throw 'runtime identity unknown' }
        }
    }
    Write-Output 'runtime-stopped=verified'
} catch {
    Write-Output 'runtime-stopped=unproven'
    exit 1
}
