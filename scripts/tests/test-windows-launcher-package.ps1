[CmdletBinding()]
param(
    [string]$OutputDirectory
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$packageScript = Join-Path $repoRoot "launcher\windows\package.ps1"
$installScript = Join-Path $repoRoot "launcher\windows\install.ps1"
$root = Join-Path ([IO.Path]::GetTempPath()) "hermes-launcher-package-smoke-$([Guid]::NewGuid().ToString('N'))"
$packageDirectory = if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    Join-Path $root "package"
} else {
    [IO.Path]::GetFullPath($OutputDirectory)
}
$installDirectory = Join-Path $root "installed"
$shortcutDirectory = Join-Path $root "shortcuts"
$initialHead = (& git -C $repoRoot rev-parse HEAD).Trim()
$initialStatus = (@(& git -C $repoRoot status --porcelain) -join "`n")
$expectedAssets = @(
    "HermesFinance.Launcher.exe",
    "hermes-finance-cat.ico",
    "prepare-runtime-dependencies.ps1",
    "launcher-schema-check.py"
)

try {
    New-Item -ItemType Directory -Force -Path $root | Out-Null

    & $packageScript -OutputDirectory $packageDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Windows launcher package script failed with exit code $LASTEXITCODE."
    }

    foreach ($asset in $expectedAssets) {
        Assert-True (Test-Path -LiteralPath (Join-Path $packageDirectory $asset) -PathType Leaf) "Packaged launcher is missing '$asset'."
    }
    foreach ($asset in @("HermesFinance.Launcher.dll", "HermesFinance.Launcher.deps.json", "HermesFinance.Launcher.runtimeconfig.json")) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $packageDirectory $asset))) "Packaged launcher is not self-contained: '$asset' was emitted."
    }

    & $installScript `
        -PackageDirectory $packageDirectory `
        -InstallDirectory $installDirectory `
        -ShortcutDirectory $shortcutDirectory `
        -SkipStartMenuShortcut
    if ($LASTEXITCODE -ne 0) {
        throw "Windows launcher install script failed with exit code $LASTEXITCODE."
    }

    $installedExecutable = Join-Path $installDirectory "HermesFinance.Launcher.exe"
    $shortcutPath = Join-Path $shortcutDirectory "Hermes Finance.lnk"
    foreach ($asset in $expectedAssets) {
        Assert-True (Test-Path -LiteralPath (Join-Path $installDirectory $asset) -PathType Leaf) "Installed launcher is missing '$asset'."
    }
    Assert-True (Test-Path -LiteralPath $shortcutPath -PathType Leaf) "Synthetic installer did not create the expected shortcut."

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    Assert-True ($shortcut.TargetPath -eq $installedExecutable) "Synthetic shortcut must target the installed packaged launcher."
    Assert-True ($shortcut.WorkingDirectory -eq $installDirectory) "Synthetic shortcut must use the installed launcher directory."
    Assert-True ($shortcut.TargetPath -ne (Join-Path $repoRoot "launcher\windows\HermesFinance.Launcher.exe")) "Synthetic shortcut must not target a checkout artifact."

    $installerSource = Get-Content -Raw $installScript
    Assert-True (-not [regex]::IsMatch($installerSource, "git\s+(pull|switch|checkout|reset)", [Text.RegularExpressions.RegexOptions]::IgnoreCase)) "Installer must not mutate Git state."
    Assert-True (-not [regex]::IsMatch((Get-Content -Raw $packageScript), "git\s+(pull|switch|checkout|reset)", [Text.RegularExpressions.RegexOptions]::IgnoreCase)) "Package script must not mutate Git state."
    Assert-True ($installerSource.IndexOf("private", [StringComparison]::OrdinalIgnoreCase) -lt 0) "Installer must not reference private data."
    Assert-True ((Get-Content -Raw $packageScript).IndexOf("private", [StringComparison]::OrdinalIgnoreCase) -lt 0) "Package script must not reference private data."
    Assert-True ((& git -C $repoRoot rev-parse HEAD).Trim() -eq $initialHead) "Package/install smoke changed the task worktree HEAD."
    Assert-True ((@(& git -C $repoRoot status --porcelain) -join "`n") -eq $initialStatus) "Package/install smoke changed tracked or untracked files in the task worktree."

    Write-Host "Windows launcher package/install smoke: PASS" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $root) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
