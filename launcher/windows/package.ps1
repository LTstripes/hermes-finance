[CmdletBinding()]
param(
    [string]$OutputDirectory
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $PSScriptRoot "artifacts\\win-x64"
}

$project = Join-Path $PSScriptRoot "HermesFinance.Launcher\\HermesFinance.Launcher.csproj"
$tests = Join-Path $PSScriptRoot "HermesFinance.Launcher.SafetyTests\\HermesFinance.Launcher.SafetyTests.csproj"

if ($null -eq (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw "Missing dependency 'dotnet'. Install the .NET 8 SDK before packaging HermesFinance.Launcher.exe."
}

& dotnet restore $project --runtime win-x64 --ignore-failed-sources -p:NuGetAudit=false
if ($LASTEXITCODE -ne 0) {
    throw "Windows launcher restore failed."
}

& dotnet restore $tests --ignore-failed-sources -p:NuGetAudit=false
if ($LASTEXITCODE -ne 0) {
    throw "Windows launcher safety-test restore failed."
}

& dotnet run --project $tests --configuration Release --no-restore
if ($LASTEXITCODE -ne 0) {
    throw "Windows launcher safety tests failed."
}

& dotnet publish $project --configuration Release --runtime win-x64 --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    --no-restore `
    --output $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Windows launcher packaging failed."
}

$executable = Join-Path $OutputDirectory "HermesFinance.Launcher.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Packaging did not produce HermesFinance.Launcher.exe."
}

Write-Host "Packaged launcher: $executable" -ForegroundColor Green
