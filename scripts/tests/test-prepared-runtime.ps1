[CmdletBinding()]
param()

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

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Write-Ascii {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $encoding = New-Object System.Text.ASCIIEncoding
    [IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $command = @("-C", $Root) + $Arguments
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git @command 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Synthetic Git command failed: git $($Arguments -join ' ')`n$output"
    }
    return $output.Trim()
}

function Invoke-PowerShellFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Script,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) {
        $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
    }
    Push-Location $WorkingDirectory
    try {
        $command = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $Script
        ) + $Arguments
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = & $powershell @command 2>&1 | Out-String
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        [pscustomobject]@{
            ExitCode = $exitCode
            Output = $output
        }
    }
    finally {
        Pop-Location
    }
}

function Write-CommandShims {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ToolDirectory
    )

    Write-Ascii -Path (Join-Path $ToolDirectory "uv.cmd") -Content @'
@echo off
>>"%HERMES_TEST_COMMAND_LOG%" echo uv %*
if /I "%~1"=="sync" if /I "%~2"=="--locked" if /I "%~3"=="--dry-run" if /I "%~4"=="--offline" (
    if exist ".venv\pyvenv.cfg" if exist ".venv\installed-packages.txt" (
        findstr /I /X /C:"synthetic-backend==1.0.0" ".venv\installed-packages.txt" >nul 2>nul
        if not errorlevel 1 exit /b 0
        echo Would reinstall the backend environment
        exit /b 0
    )
    echo Would create the backend environment
    exit /b 0
)
if /I "%~1"=="sync" if /I "%~2"=="--locked" (
    if not exist ".venv" mkdir ".venv"
    if not exist ".venv\Scripts" mkdir ".venv\Scripts"
    >".venv\pyvenv.cfg" echo synthetic backend environment
    >".venv\Scripts\python.exe" echo synthetic backend python
    >".venv\installed-packages.txt" echo synthetic-backend==1.0.0
    exit /b 0
)
if /I "%~1"=="pip" if /I "%~2"=="list" (
    if exist ".venv\installed-packages.txt" type ".venv\installed-packages.txt"
    exit /b 0
)
echo unexpected uv invocation %* 1>&2
exit /b 9
'@

    Write-Ascii -Path (Join-Path $ToolDirectory "npm.cmd") -Content @'
@echo off
>>"%HERMES_TEST_COMMAND_LOG%" echo npm %*
if /I "%~1"=="ci" (
    if not exist "node_modules" mkdir "node_modules"
    >"node_modules\.package-lock.json" echo {"name":"synthetic-frontend"}
    exit /b 0
)
if /I "%~1"=="ls" (
    echo {"name":"hermes-finance-frontend","version":"0.0.0"}
    exit /b 0
)
if /I "%~1"=="run" if /I "%~2"=="build" (
    if not exist "dist" mkdir "dist"
    >"dist\index.html" echo Hermes Finance
    >"dist\assets.txt" echo synthetic bundle
    exit /b 0
)
echo unexpected npm invocation %* 1>&2
exit /b 9
'@
}

function New-SyntheticCheckout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$PrepareScript,
        [Parameter(Mandatory = $true)]
        [string]$DependencyScript
    )

    foreach ($directory in @(
        $Checkout,
        (Join-Path $Checkout "scripts"),
        (Join-Path $Checkout "backend"),
        (Join-Path $Checkout "frontend\src")
    )) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }

    Copy-Item -LiteralPath $PrepareScript -Destination (Join-Path $Checkout "scripts\prepare-runtime.ps1")
    Copy-Item -LiteralPath $DependencyScript -Destination (Join-Path $Checkout "scripts\prepare-runtime-dependencies.ps1")
    Write-Utf8NoBom -Path (Join-Path $Checkout ".gitignore") -Content @'
.hermes-runtime-prepared.json*
backend/.venv/
frontend/node_modules/
frontend/dist/
'@
    Write-Utf8NoBom -Path (Join-Path $Checkout "backend\pyproject.toml") -Content "[project]`nname = 'synthetic-backend'`n"
    Write-Utf8NoBom -Path (Join-Path $Checkout "backend\uv.lock") -Content "version = 1`n"
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\package.json") -Content '{"name":"hermes-finance-frontend","version":"0.0.0"}'
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\package-lock.json") -Content '{"name":"hermes-finance-frontend","lockfileVersion":3}'
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\index.html") -Content "<div id='root'>Hermes Finance</div>`n"
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\tsconfig.json") -Content '{}'
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\tsconfig.app.json") -Content '{}'
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\tsconfig.node.json") -Content '{}'
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\vite.config.ts") -Content "export default {};`n"
    Write-Utf8NoBom -Path (Join-Path $Checkout "frontend\src\App.tsx") -Content "export const App = () => 'Hermes Finance';`n"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$prepareScript = Join-Path $repoRoot "scripts\prepare-runtime.ps1"
$dependencyScript = Join-Path $repoRoot "scripts\prepare-runtime-dependencies.ps1"
$startScript = Join-Path $repoRoot "scripts\start-local.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("hermes-r09-ops01-" + [guid]::NewGuid().ToString("N"))
$checkout = Join-Path $tempRoot "Synthetic Runtime With Spaces"
$toolDirectory = Join-Path $tempRoot "External Tools With Spaces"
$commandLog = Join-Path $tempRoot "commands.log"
$originalPath = [Environment]::GetEnvironmentVariable("Path", "Process")
$originalCommandLog = [Environment]::GetEnvironmentVariable("HERMES_TEST_COMMAND_LOG", "Process")

try {
    New-Item -ItemType Directory -Force -Path $toolDirectory | Out-Null
    New-SyntheticCheckout -Checkout $checkout -PrepareScript $prepareScript -DependencyScript $dependencyScript
    Write-CommandShims -ToolDirectory $toolDirectory
    [Environment]::SetEnvironmentVariable("HERMES_TEST_COMMAND_LOG", $commandLog, "Process")
    $gitDirectory = Split-Path -Parent (Get-Command git.exe -ErrorAction Stop).Source
    $powerShellDirectory = Split-Path -Parent (Get-Command powershell.exe -ErrorAction Stop).Source
    $testPathEntries = @(
        $toolDirectory,
        $gitDirectory,
        $powerShellDirectory,
        (Join-Path $env:SystemRoot "System32")
    ) | Select-Object -Unique
    $testPath = [string]::Join([IO.Path]::PathSeparator, @($testPathEntries))
    [Environment]::SetEnvironmentVariable("Path", $testPath, "Process")
    $env:Path = $testPath

    Invoke-Git -Root $checkout -Arguments @("init", "--quiet") | Out-Null
    Invoke-Git -Root $checkout -Arguments @("config", "user.name", "Hermes OPS01 Test") | Out-Null
    Invoke-Git -Root $checkout -Arguments @("config", "user.email", "hermes-ops01-test-identity") | Out-Null
    Invoke-Git -Root $checkout -Arguments @("add", ".") | Out-Null
    Invoke-Git -Root $checkout -Arguments @("commit", "--quiet", "-m", "initial synthetic runtime") | Out-Null

    $missing = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($missing.ExitCode -ne 0) "Missing prepared state must block validation."
    Assert-True ($missing.Output -match "Prepared runtime state is missing") "Missing state must be actionable."
    Assert-True ($missing.Output -match "prepare-runtime\.ps1") "Missing state must name the explicit Prepare operation."
    Assert-True (-not (Test-Path -LiteralPath $commandLog -PathType Leaf)) "Validation must not run dependency commands."

    $prepare = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Prepare")
    Assert-True ($prepare.ExitCode -eq 0) "Explicit Prepare must succeed: $($prepare.Output)"
    Assert-True ($prepare.Output -match "runtime=prepared") "Prepare must report a prepared runtime."

    $statePath = Join-Path $checkout ".hermes-runtime-prepared.json"
    Assert-True (Test-Path -LiteralPath $statePath -PathType Leaf) "Prepare must write the runtime proof."
    $stateText = Get-Content -LiteralPath $statePath -Raw
    Assert-True ($stateText -notmatch [regex]::Escape($checkout)) "Prepared proof must not contain the checkout path."
    Assert-True ($stateText -notmatch "secret|token|finance\.db") "Prepared proof must not contain secrets or financial data."
    $state = $stateText | ConvertFrom-Json
    foreach ($field in @(
        "schema_version",
        "git_head",
        "backend_pyproject_sha256",
        "backend_uv_lock_sha256",
        "backend_environment_sha256",
        "backend_environment_packages_sha256",
        "frontend_build_inputs_sha256",
        "frontend_dependency_tree_sha256",
        "frontend_dist_sha256"
    )) {
        Assert-True ($null -ne $state.PSObject.Properties[$field]) "Prepared proof is missing '$field'."
    }
    Assert-True ((Invoke-Git -Root $checkout -Arguments @("status", "--porcelain")) -eq "") "Prepare must leave Git clean."

    $valid = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($valid.ExitCode -eq 0) "Prepared state must validate: $($valid.Output)"
    $commandLinesAfterValidation = @(Get-Content -LiteralPath $commandLog)
    Assert-True (@($commandLinesAfterValidation | Where-Object { $_ -eq "uv sync --locked" }).Count -eq 1) "Validation must not sync the backend environment."
    $stateAfterFirstPrepare = Get-Content -LiteralPath $statePath -Raw

    $prepareAgain = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Prepare")
    Assert-True ($prepareAgain.ExitCode -eq 0) "Repeated Prepare must be idempotent: $($prepareAgain.Output)"
    Assert-True ((Get-Content -LiteralPath $statePath -Raw) -eq $stateAfterFirstPrepare) "Unchanged Prepare must produce the same proof."
    $commandLines = @(Get-Content -LiteralPath $commandLog)
    Assert-True (@($commandLines | Where-Object { $_ -eq "uv sync --locked" }).Count -eq 1) "Repeated Prepare must not reinstall the backend."
    Assert-True (@($commandLines | Where-Object { $_ -eq "npm ci --no-audit --no-fund" }).Count -eq 1) "Repeated Prepare must not reinstall the frontend."
    Assert-True (@($commandLines | Where-Object { $_ -eq "npm run build" }).Count -eq 2) "Each explicit Prepare may rebuild the requested frontend proof."

    $backendInventoryPath = Join-Path $checkout "backend\.venv\installed-packages.txt"
    Write-Utf8NoBom -Path $backendInventoryPath -Content "synthetic-backend==9.9.9`n"
    $staleBackendEnvironment = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($staleBackendEnvironment.ExitCode -ne 0) "A mutated backend package environment must invalidate prepared state."
    Assert-True ($staleBackendEnvironment.Output -match "backend_environment_packages_sha256") "Backend package staleness must identify the package inventory proof."
    $repairBackendEnvironment = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Prepare")
    Assert-True ($repairBackendEnvironment.ExitCode -eq 0) "Prepare must repair a mutated backend package environment: $($repairBackendEnvironment.Output)"
    Assert-True ((Get-Content -LiteralPath $backendInventoryPath -Raw).Trim() -eq "synthetic-backend==1.0.0") "Prepare must recreate the expected backend package inventory."
    $backendEnvironmentValid = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($backendEnvironmentValid.ExitCode -eq 0) "Repaired backend package environment must validate: $($backendEnvironmentValid.Output)"

    $repairMode = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Repair")
    Assert-True ($repairMode.ExitCode -ne 0) "OPS01 must not expose the future -Repair operation."

    $sourcePath = Join-Path $checkout "frontend\src\App.tsx"
    $originalSource = [IO.File]::ReadAllBytes($sourcePath)
    Write-Utf8NoBom -Path $sourcePath -Content "export const App = () => 'Changed';`n"
    $dirty = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($dirty.ExitCode -ne 0) "Uncommitted source changes must invalidate prepared state."
    Assert-True ($dirty.Output -match "uncommitted|untracked") "Dirty checkout rejection must be clear."
    [IO.File]::WriteAllBytes($sourcePath, $originalSource)
    $restored = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($restored.ExitCode -eq 0) "Restoring the exact source must restore validity: $($restored.Output)"

    Write-Utf8NoBom -Path $sourcePath -Content "export const App = () => 'Committed change';`n"
    Invoke-Git -Root $checkout -Arguments @("add", ".") | Out-Null
    Invoke-Git -Root $checkout -Arguments @("commit", "--quiet", "-m", "change synthetic source") | Out-Null
    $staleCommit = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($staleCommit.ExitCode -ne 0) "A changed commit must invalidate prepared state."
    Assert-True ($staleCommit.Output -match "git_head") "Commit staleness must identify the changed code identity."

    $reprepare = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Prepare")
    Assert-True ($reprepare.ExitCode -eq 0) "Prepare must refresh state for a new commit: $($reprepare.Output)"
    $distIndex = Join-Path $checkout "frontend\dist\index.html"
    $originalDist = [IO.File]::ReadAllBytes($distIndex)
    Write-Utf8NoBom -Path $distIndex -Content "Tampered bundle`n"
    $staleBundle = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($staleBundle.ExitCode -ne 0) "A changed frontend bundle must invalidate prepared state."
    Assert-True ($staleBundle.Output -match "frontend_dist_sha256") "Bundle staleness must identify the changed artifact."
    [IO.File]::WriteAllBytes($distIndex, $originalDist)
    $bundleRestored = Invoke-PowerShellFile `
        -Script (Join-Path $checkout "scripts\prepare-runtime.ps1") `
        -WorkingDirectory $repoRoot `
        -Arguments @("-Checkout", $checkout, "-Validate")
    Assert-True ($bundleRestored.ExitCode -eq 0) "Restoring the exact bundle must restore validity: $($bundleRestored.Output)"

    $startSource = Get-Content -LiteralPath $startScript -Raw
    Assert-True ($startSource -notmatch "npm\s+(ci|run\s+build)") "Ordinary Start must not install or build frontend dependencies."
    Assert-True ($startSource -notmatch "uv\s+sync") "Ordinary Start must not sync backend dependencies."
    Assert-True ($startSource -match "--locked") "Ordinary Start must use the locked backend runtime."
    Assert-True ($startSource -match "--offline") "Ordinary Start must remain offline."
    Assert-True ($startSource -match "--no-sync") "Ordinary Start must not let uv implicitly sync."
    Assert-True ($startSource -match "127\.0\.0\.1") "Loopback binding must remain explicit."
    Assert-True ($startSource.IndexOf("Invoke-PreparedRuntimeValidation", [StringComparison]::Ordinal) -lt $startSource.IndexOf('-FilePath $uv', [StringComparison]::Ordinal)) "Prepared validation must happen before backend launch."

    Write-Host "Prepared runtime / deterministic start regression: PASS" -ForegroundColor Green
}
finally {
    [Environment]::SetEnvironmentVariable("Path", $originalPath, "Process")
    [Environment]::SetEnvironmentVariable("HERMES_TEST_COMMAND_LOG", $originalCommandLog, "Process")
    $env:Path = $originalPath
    $env:HERMES_TEST_COMMAND_LOG = $originalCommandLog
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
