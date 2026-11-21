[CmdletBinding()]
param([switch]$ValidationChild)

# Launched from Stable's working directory with the same no-profile -File
# invocation as Start. Its prepared-state validator runs one PowerShell deeper.
$ErrorActionPreference = 'Stop'
if ($ValidationChild) {
    try {
        $sha = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
        if ($sha -notmatch '^[0-9a-f]{64}$') { exit 12 }
    }
    catch { exit 12 }
    try { $null = Get-Command git, uv, ConvertFrom-Json -ErrorAction Stop }
    catch { exit 13 }
    exit 0
}

try {
    $validationShell = (Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
    & $validationShell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -ValidationChild
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $null = Get-Command Get-NetTCPConnection, Invoke-RestMethod, npm.cmd -ErrorAction Stop
}
catch { exit 14 }
exit 0
