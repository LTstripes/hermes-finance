[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Script,
    [Parameter(Mandatory = $true)]
    [string]$ArgumentsJson,
    [Parameter(Mandatory = $true)]
    [string]$OwnershipToken
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$receivedToken = [Console]::In.ReadLine()
if (-not [string]::Equals($receivedToken, $OwnershipToken, [StringComparison]::Ordinal)) {
    Write-Error "Recovery runtime ownership was not established."
    exit 97
}

try {
    $parsedArguments = ConvertFrom-Json -InputObject $ArgumentsJson
    if (-not ($parsedArguments -is [Array]) -or $parsedArguments.Count -gt 32) {
        throw "Recovery runtime arguments are invalid."
    }
    $arguments = New-Object string[] $parsedArguments.Count
    for ($index = 0; $index -lt $parsedArguments.Count; $index++) {
        if (-not ($parsedArguments[$index] -is [string])) {
            throw "Recovery runtime arguments are invalid."
        }
        $arguments[$index] = [string]$parsedArguments[$index]
    }
    $childPowerShell = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path -LiteralPath $childPowerShell -PathType Leaf)) {
        throw "Recovery runtime PowerShell is unavailable."
    }
    # Array splatting into a PowerShell script treats '-Name' values as positional
    # strings. Cross a native-process boundary so the child host parses the exact
    # validated argument vector as command-line parameters and remains in the job.
    & $childPowerShell `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $Script `
        @arguments
    exit $LASTEXITCODE
}
catch {
    Write-Error "Recovery runtime operation failed."
    exit 1
}
