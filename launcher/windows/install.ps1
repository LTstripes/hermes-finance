[CmdletBinding()]
param(
    [string]$InstallDirectory,
    [string]$PackageDirectory,
    [string]$ShortcutDirectory,
    [switch]$SkipStartMenuShortcut
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $InstallDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "HermesFinance\launcher"
}

$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$packageDirectoryWasProvided = -not [string]::IsNullOrWhiteSpace($PackageDirectory)
if ($packageDirectoryWasProvided) {
    $PackageDirectory = [IO.Path]::GetFullPath($PackageDirectory)
    if (-not (Test-Path -LiteralPath $PackageDirectory -PathType Container)) {
        throw "Cannot install launcher: package directory '$PackageDirectory' does not exist."
    }
} else {
    $PackageDirectory = Join-Path $PSScriptRoot "artifacts\install-staging"
    $packageScript = Join-Path $PSScriptRoot "package.ps1"

    & $packageScript -OutputDirectory $PackageDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Launcher packaging failed; installation was not attempted."
    }
}

New-Item -ItemType Directory -Force -Path $InstallDirectory | Out-Null
foreach ($asset in @("HermesFinance.Launcher.exe", "hermes-finance-cat.ico", "prepare-runtime-dependencies.ps1", "launcher-schema-check.py")) {
    $source = Join-Path $PackageDirectory $asset
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

$desktop = if ([string]::IsNullOrWhiteSpace($ShortcutDirectory)) {
    [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
} else {
    [IO.Path]::GetFullPath($ShortcutDirectory)
}
if (-not [string]::IsNullOrWhiteSpace($desktop)) {
    New-Item -ItemType Directory -Force -Path $desktop | Out-Null
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
