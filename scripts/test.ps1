# Run tests. Never modifies source files.
#   .\scripts\test.ps1                      # backend pytest + frontend vitest + typecheck + build (as before)
#   .\scripts\test.ps1 -Backend             # backend pytest only
#   .\scripts\test.ps1 -Frontend [-ChangedSince <sha>]   # vitest (optionally --changed <sha>) + tsc -b, no vite build
#   .\scripts\test.ps1 -Paths backend/tests/test_x.py,frontend/src/a.test.ts
#   .\scripts\test.ps1 -Full                # everything incl. production build
[CmdletBinding()]
param([switch]$Backend, [switch]$Frontend, [switch]$Full, [string[]]$Paths, [string]$ChangedSince, [switch]$Build, [int]$Timeout = 0)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $PSScriptRoot "check-common.ps1")
$backendDir = Join-Path $repoRoot "backend"; $frontendDir = Join-Path $repoRoot "frontend"

try {
    $scope = Resolve-CheckScope -Backend:$Backend -Frontend:$Frontend -Full:$Full -Paths $Paths
    $tools = Assert-ScopeReady -Scope $scope -RepoRoot $repoRoot
    $legacyDefault = -not ($Backend -or $Frontend -or $Full -or $Paths)
    $doBuild = $Full -or $Build -or $legacyDefault
    Write-Host ("Plan: backend={0} frontend={1} full={2} build={3} bePaths=[{4}] fePaths=[{5}] changedSince={6}" -f $scope.Backend, $scope.Frontend, $scope.Full, $doBuild, ($scope.BackendPaths -join ' '), ($scope.FrontendPaths -join ' '), $ChangedSince)

    if ($scope.Backend) {
        $uv = $tools.uv
        Push-Location $backendDir
        try {
            Invoke-NativeStep -Label "Checking backend lockfile" -Action { & $uv lock --check }
            $targets = @($scope.BackendPaths)
            Invoke-NativeStep -Label "Running backend tests $($targets -join ' ')" -Action {
                if ($Timeout -gt 0) { & $uv run --locked --with pytest-timeout python -I -m pytest -q -p timeout "--timeout=$Timeout" @targets }
                else { & $uv run --locked python -I -m pytest -q @targets }
            }
        }
        finally { Pop-Location }
    }

    if ($scope.Frontend) {
        $npm = $tools.npm
        Push-Location $frontendDir
        try {
            $vArgs = @()
            if ($ChangedSince -and -not $Full) { $vArgs += "--changed=$ChangedSince" }
            $vArgs += @($scope.FrontendPaths)
            Invoke-NativeStep -Label "Running frontend tests $($vArgs -join ' ')" -Action { & $npm test -- @vArgs }
            if ($doBuild) {
                Invoke-NativeStep -Label "Building frontend (tsc -b && vite build)" -Action { & $npm run build }
            }
            else {
                Invoke-NativeStep -Label "Type-checking frontend (tsc -b)" -Action { & $npm exec -- tsc -b }
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
