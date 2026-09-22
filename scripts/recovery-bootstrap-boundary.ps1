[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$script = [Environment]::GetEnvironmentVariable(
    "HERMES_RECOVERY_BOOTSTRAP_SCRIPT",
    "Process"
)
$argumentsJson = [Environment]::GetEnvironmentVariable(
    "HERMES_RECOVERY_BOOTSTRAP_ARGUMENTS_JSON",
    "Process"
)
$ownershipToken = [Environment]::GetEnvironmentVariable(
    "HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN",
    "Process"
)
if ($ownershipToken -notmatch '^[0-9a-f]{64}$') {
    exit 97
}

try {
    $readyEventName = "Local\HermesRecoveryBootstrapReady-$ownershipToken"
    try {
        $readyEvent = [Threading.EventWaitHandle]::OpenExisting($readyEventName)
    }
    catch {
        exit 97
    }
    try {
        if (-not $readyEvent.WaitOne(30000)) {
            exit 97
        }
    }
    finally {
        $readyEvent.Dispose()
    }
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
        throw "Recovery bootstrap script is unavailable."
    }
    $parsedArguments = ConvertFrom-Json -InputObject $argumentsJson
    if (-not ($parsedArguments -is [Array]) -or $parsedArguments.Count -gt 64) {
        throw "Recovery bootstrap arguments are invalid."
    }
    $arguments = New-Object string[] $parsedArguments.Count
    for ($index = 0; $index -lt $parsedArguments.Count; $index++) {
        if (-not ($parsedArguments[$index] -is [string])) {
            throw "Recovery bootstrap arguments are invalid."
        }
        $arguments[$index] = [string]$parsedArguments[$index]
    }
    $childPowerShell = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $childPowerShell -PathType Leaf)) {
        throw "Recovery bootstrap PowerShell is unavailable."
    }
    & $childPowerShell `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $script `
        @arguments
    exit $LASTEXITCODE
}
catch {
    exit 1
}
