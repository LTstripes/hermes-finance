[CmdletBinding()]
param(
    [string]$InstallDirectory,
    [switch]$SkipStartMenuShortcut
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $InstallDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "HermesFinance\launcher"
}

$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$stagingDirectory = Join-Path $PSScriptRoot "artifacts\install-staging"
$packageScript = Join-Path $PSScriptRoot "package.ps1"

& $packageScript -OutputDirectory $stagingDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Launcher packaging failed; installation was not attempted."
}

New-Item -ItemType Directory -Force -Path $InstallDirectory | Out-Null
foreach ($asset in @("HermesFinance.Launcher.exe", "hermes-finance-cat.ico", "prepare-runtime-dependencies.ps1", "launcher-schema-check.py")) {
    $source = Join-Path $stagingDirectory $asset
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Cannot install launcher: packaged asset '$asset' is missing."
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $InstallDirectory $asset) -Force
}

$executable = Join-Path $InstallDirectory "HermesFinance.Launcher.exe"
$shell = New-Object -ComObject WScript.Shell

function New-LauncherShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $executable
    $shortcut.WorkingDirectory = $InstallDirectory
    $shortcut.IconLocation = "$executable,0"
    $shortcut.Description = "Hermes Finance"
    $shortcut.Save()
}

$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if (-not [string]::IsNullOrWhiteSpace($desktop)) {
    New-LauncherShortcut -Path (Join-Path $desktop "Hermes Finance.lnk")
}

if (-not $SkipStartMenuShortcut) {
    $programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
    if (-not [string]::IsNullOrWhiteSpace($programs)) {
        $startMenuDirectory = Join-Path $programs "Hermes Finance"
        New-Item -ItemType Directory -Force -Path $startMenuDirectory | Out-Null
        New-LauncherShortcut -Path (Join-Path $startMenuDirectory "Hermes Finance.lnk")
    }
}

Write-Host "Installed Hermes Finance launcher: $executable" -ForegroundColor Green
