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
$inputStream = [Console]::OpenStandardInput()
$ownershipBytes = New-Object byte[] 65
$offset = 0
while ($offset -lt $ownershipBytes.Length) {
    $read = $inputStream.Read($ownershipBytes, $offset, $ownershipBytes.Length - $offset)
    if ($read -eq 0) {
        break
    }
    $offset += $read
}
$ownershipToken = [Text.Encoding]::ASCII.GetString($ownershipBytes, 0, 64)
if (
    $offset -ne $ownershipBytes.Length -or
    $ownershipBytes[64] -ne 10 -or
    $ownershipToken -notmatch '^[0-9a-f]{64}$'
) {
    exit 97
}

try {
    $env:HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN = $ownershipToken
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
