# Launch a .ps1 through Windows PowerShell 5.1 without losing paths that contain spaces.
# Do not use Start-Process -ArgumentList @(..., $path): Windows PowerShell 5.1 joins
# that array with spaces and does not quote, so -File is truncated at the first space.

Set-StrictMode -Version 2.0

function Get-WindowsPowerShellExe {
    $candidate = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Windows PowerShell 5.1 was not found at '$candidate'."
    }
    return $candidate
}

function Get-WindowsPowerShellFileCommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    $quotedFile = '"' + ($FilePath.Replace('"', '\"')) + '"'
    return "-NoProfile -ExecutionPolicy Bypass -File $quotedFile"
}

function Start-WindowsPowerShellFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string]$WorkingDirectory
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "PowerShell file not found at '$FilePath'."
    }
    if (-not $WorkingDirectory) {
        $WorkingDirectory = [IO.Path]::GetDirectoryName($FilePath)
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Get-WindowsPowerShellExe
    $psi.Arguments = Get-WindowsPowerShellFileCommandLine -FilePath $FilePath
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $false

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    if (-not $process.Start()) {
        throw "Failed to start Windows PowerShell for '$FilePath'."
    }
    return $process
}
