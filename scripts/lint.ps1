# Lint checks. Never modifies files.
#   .\scripts\lint.ps1                 # backend + frontend (as before)
#   .\scripts\lint.ps1 -Backend | -Frontend | -Full
#   .\scripts\lint.ps1 -Paths backend/app/x.py,frontend/src/y.ts   # only listed files
[CmdletBinding()]
param([switch]$Backend, [switch]$Frontend, [switch]$Full, [string[]]$Paths)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $PSScriptRoot "check-common.ps1")
$backendDir = Join-Path $repoRoot "backend"; $frontendDir = Join-Path $repoRoot "frontend"

try {
    $scope = Resolve-CheckScope -Backend:$Backend -Frontend:$Frontend -Full:$Full -Paths $Paths
    $tools = Assert-ScopeReady -Scope $scope -RepoRoot $repoRoot
    Write-Host ("Plan: backend={0} frontend={1} bePaths=[{2}] fePaths=[{3}]" -f $scope.Backend, $scope.Frontend, ($scope.BackendPaths -join ' '), ($scope.FrontendPaths -join ' '))
    if ($scope.Backend) {
        $uv = $tools.uv
        $t = @($scope.BackendPaths); if ($t.Count -eq 0) { $t = @('.') }
        Push-Location $backendDir
        try { Invoke-NativeStep -Label "Linting backend" -Action { & $uv run --locked ruff check @t } }
        finally { Pop-Location }
    }
    if ($scope.Frontend) {
        $npm = $tools.npm
        $t = @($scope.FrontendPaths)
        Push-Location $frontendDir
        try {
            Invoke-NativeStep -Label "Linting frontend" -Action {
                if ($t.Count -gt 0) { & $npm exec -- biome lint @t } else { & $npm run lint }
            }
        }
        finally { Pop-Location }
    }
    Write-Host "Selected checks passed." -ForegroundColor Green
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
