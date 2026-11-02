# Shared helpers for scripts/test.ps1, lint.ps1, format-check.ps1.
# Scope: -Full (everything, CI-like), -Backend, -Frontend, -Paths <files>.
# No scope flags = Backend + Frontend (previous default behavior).
Set-StrictMode -Version 2.0

function Get-RequiredCommand {
    param([Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][string]$InstallHint)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Missing dependency '$Name'. $InstallHint" }
    return $command.Source
}

function Invoke-NativeStep {
    param([Parameter(Mandatory = $true)][string]$Label, [Parameter(Mandatory = $true)][scriptblock]$Action)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE." }
}

function Resolve-CheckScope {
    param([switch]$Backend, [switch]$Frontend, [switch]$Full, [string[]]$Paths)
    $split = @()
    if ($Paths) { $split = @($Paths | ForEach-Object { $_ -split '[ ,;]+' } | Where-Object { $_ } | ForEach-Object { $_ -replace '\\', '/' }) }
    $bePaths = @($split | Where-Object { $_ -like 'backend/*' } | ForEach-Object { $_.Substring(8) })
    $fePaths = @($split | Where-Object { $_ -like 'frontend/*' } | ForEach-Object { $_.Substring(9) })
    $useBackend = [bool]($Full -or $Backend -or $bePaths.Count -gt 0)
    $useFrontend = [bool]($Full -or $Frontend -or $fePaths.Count -gt 0)
    if (-not $Full -and -not $Backend -and -not $Frontend -and $split.Count -eq 0) { $useBackend = $true; $useFrontend = $true }
    if ($Full) { $bePaths = @(); $fePaths = @() }
    return [pscustomobject]@{ Backend = $useBackend; Frontend = $useFrontend; Full = [bool]$Full; BackendPaths = $bePaths; FrontendPaths = $fePaths }
}

function Assert-ScopeReady {
    param([Parameter(Mandatory = $true)]$Scope, [string]$RepoRoot)
    $backendDir = Join-Path $RepoRoot "backend"; $frontendDir = Join-Path $RepoRoot "frontend"
    $tools = @{}
    if ($Scope.Backend) {
        $tools.uv = Get-RequiredCommand -Name "uv" -InstallHint "Install uv from https://docs.astral.sh/uv/."
        if (-not (Test-Path (Join-Path $backendDir "pyproject.toml") -PathType Leaf)) { throw "Backend project not found at '$backendDir'." }
    }
    if ($Scope.Frontend) {
        $tools.npm = Get-RequiredCommand -Name "npm.cmd" -InstallHint "Install Node.js 22.22 or newer from https://nodejs.org/."
        if (-not (Test-Path (Join-Path $frontendDir "package.json") -PathType Leaf)) { throw "Frontend project not found at '$frontendDir'." }
        if (-not (Test-Path (Join-Path $frontendDir "node_modules") -PathType Container)) { throw "Frontend dependencies are missing. Run 'cd frontend' and then 'npm ci'." }
    }
    return $tools
}
