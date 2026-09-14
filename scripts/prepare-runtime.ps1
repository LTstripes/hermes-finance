[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Checkout,
    [switch]$Prepare,
    [Alias("Check")]
    [switch]$Validate
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$requestedModes = 0
if ($Prepare) {
    $requestedModes++
}
if ($Validate) {
    $requestedModes++
}
if ($requestedModes -gt 1) {
    throw "Choose only one of -Prepare or -Validate."
}
if ($requestedModes -eq 0) {
    throw "Choose one of -Prepare or -Validate."
}

$preparedStateFileName = ".hermes-runtime-prepared.json"

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Missing dependency '$Name'. $InstallHint"
    }

    return $command.Source
}

function Invoke-CapturedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    Push-Location $WorkingDirectory
    try {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = & $FilePath @ArgumentList 2>&1 | Out-String
            [pscustomobject]@{
                ExitCode = $LASTEXITCODE
                Output = $output
            }
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-ChildPowerShell {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PowerShell,
        [Parameter(Mandatory = $true)]
        [string]$Script,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $Script
    ) + $ArgumentList
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $PowerShell @arguments 2>&1 | Out-String
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

function Get-FileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required runtime file is missing: $Path"
    }

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-BackendPackageInventorySha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Uv
    )

    $backend = Join-Path $Root "backend"
    $python = Join-Path $backend ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Locked backend Python environment is missing. Run the explicit Prepare command."
    }

    $inventoryResult = Invoke-CapturedCommand `
        -FilePath $Uv `
        -WorkingDirectory $backend `
        -ArgumentList @("pip", "list", "--python", $python, "--format", "freeze", "--offline")
    if ($inventoryResult.ExitCode -ne 0) {
        throw "Backend package inventory could not be read: $($inventoryResult.Output.Trim())"
    }

    $inventoryLines = @(
        $inventoryResult.Output -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { $_.ToLowerInvariant() } |
            Sort-Object -Unique
    )
    if ($inventoryLines.Count -eq 0) {
        throw "Backend package inventory is empty. Run the explicit Prepare command."
    }

    return Get-TextSha256 -Text ([string]::Join("`n", $inventoryLines))
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $rootPrefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime fingerprint path escapes its checkout: $Path"
    }

    return $resolvedPath.Substring($rootPrefix.Length).Replace("\", "/")
}

function Get-FileManifestSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string[]]$RelativePaths
    )

    $entries = New-Object System.Collections.Generic.List[string]
    foreach ($relativePath in $RelativePaths) {
        $path = Join-Path $Root ($relativePath -replace "/", "\")
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $normalizedPath = (Get-RelativePath -Root $Root -Path $path).ToLowerInvariant()
            $entries.Add("$normalizedPath|$(Get-FileSha256 -Path $path)")
            continue
        }

        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "Required runtime input is missing: $path"
        }

        $files = @(Get-ChildItem -LiteralPath $path -File -Recurse | Sort-Object FullName)
        foreach ($file in $files) {
            $normalizedPath = (Get-RelativePath -Root $Root -Path $file.FullName).ToLowerInvariant()
            $entries.Add("$normalizedPath|$(Get-FileSha256 -Path $file.FullName)")
        }
    }

    $manifest = [string]::Join("`n", @($entries | Sort-Object))
    return Get-TextSha256 -Text $manifest
}

function Get-DirectoryManifestSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Prepared frontend bundle is missing: $Root"
    }

    $files = @(Get-ChildItem -LiteralPath $Root -File -Recurse | Sort-Object FullName)
    if ($files.Count -eq 0) {
        throw "Prepared frontend bundle is empty: $Root"
    }

    $entries = New-Object System.Collections.Generic.List[string]
    foreach ($file in $files) {
        $normalizedPath = (Get-RelativePath -Root $Root -Path $file.FullName).ToLowerInvariant()
        $entries.Add("$normalizedPath|$(Get-FileSha256 -Path $file.FullName)")
    }

    $manifest = [string]::Join("`n", @($entries | Sort-Object))
    return Get-TextSha256 -Text $manifest
}

function Assert-DependencyMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    foreach ($required in @(
        (Join-Path $Root "backend\pyproject.toml"),
        (Join-Path $Root "backend\uv.lock"),
        (Join-Path $Root "frontend\package.json"),
        (Join-Path $Root "frontend\package-lock.json")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required dependency metadata is missing: $required"
        }
    }
}

function Get-BuildInputPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Frontend
    )

    $paths = @(
        "package.json",
        "package-lock.json",
        "index.html",
        "tsconfig.json",
        "tsconfig.app.json",
        "tsconfig.node.json",
        "vite.config.ts",
        "src"
    )
    $public = Join-Path $Frontend "public"
    if (Test-Path -LiteralPath $public -PathType Container) {
        $paths += "public"
    }
    return $paths
}

function Assert-BuildMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $frontend = Join-Path $Root "frontend"
    foreach ($required in @(
        (Join-Path $frontend "index.html"),
        (Join-Path $frontend "tsconfig.json"),
        (Join-Path $frontend "tsconfig.app.json"),
        (Join-Path $frontend "tsconfig.node.json"),
        (Join-Path $frontend "vite.config.ts")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required frontend build input is missing: $required"
        }
    }
    $sourceDirectory = Join-Path $frontend "src"
    if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
        throw "Required frontend build input is missing: $sourceDirectory"
    }
}

function Get-GitState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Git
    )

    $headResult = Invoke-CapturedCommand -FilePath $Git -WorkingDirectory $Root -ArgumentList @("rev-parse", "--verify", "HEAD")
    if ($headResult.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($headResult.Output)) {
        throw "Checkout code identity cannot be read. Run the preparation command from a Git checkout."
    }

    $head = $headResult.Output.Trim().ToLowerInvariant()
    if ($head -notmatch "^[0-9a-f]{40,64}$") {
        throw "Checkout code identity is invalid. Run the preparation command from a Git checkout."
    }

    $statusResult = Invoke-CapturedCommand -FilePath $Git -WorkingDirectory $Root -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
    if ($statusResult.ExitCode -ne 0) {
        throw "Checkout status cannot be read. Run the preparation command from a Git checkout."
    }
    if (-not [string]::IsNullOrWhiteSpace($statusResult.Output)) {
        throw "Checkout has uncommitted or untracked changes; commit or restore them, then run the explicit Prepare command."
    }

    return [pscustomobject]@{
        Head = $head
    }
}

function Get-PreparedRuntimeSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Git,
        [Parameter(Mandatory = $true)]
        [string]$Uv
    )

    Assert-DependencyMetadata -Root $Root
    Assert-BuildMetadata -Root $Root
    $gitState = Get-GitState -Root $Root -Git $Git
    $frontend = Join-Path $Root "frontend"
    $backend = Join-Path $Root "backend"
    $frontendDist = Join-Path $frontend "dist"
    $backendEnvironmentMarker = Join-Path $backend ".venv\pyvenv.cfg"
    $frontendDependencyMarker = Join-Path $frontend "node_modules\.package-lock.json"

    if (-not (Test-Path -LiteralPath $backendEnvironmentMarker -PathType Leaf)) {
        throw "Locked backend environment is missing. Run the explicit Prepare command."
    }
    if (-not (Test-Path -LiteralPath $frontendDependencyMarker -PathType Leaf)) {
        throw "Locked frontend environment is missing. Run the explicit Prepare command."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html") -PathType Leaf)) {
        throw "Prepared frontend bundle is missing. Run the explicit Prepare command."
    }

    return [pscustomobject][ordered]@{
        schema_version = 2
        git_head = $gitState.Head
        backend_pyproject_sha256 = Get-FileSha256 -Path (Join-Path $backend "pyproject.toml")
        backend_uv_lock_sha256 = Get-FileSha256 -Path (Join-Path $backend "uv.lock")
        backend_environment_sha256 = Get-FileSha256 -Path $backendEnvironmentMarker
        backend_environment_packages_sha256 = Get-BackendPackageInventorySha256 -Root $Root -Uv $Uv
        frontend_build_inputs_sha256 = Get-FileManifestSha256 -Root $frontend -RelativePaths (Get-BuildInputPaths -Frontend $frontend)
        frontend_dependency_tree_sha256 = Get-FileSha256 -Path $frontendDependencyMarker
        frontend_dist_sha256 = Get-DirectoryManifestSha256 -Root $frontendDist
    }
}

function Get-PreparedStatePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    return Join-Path $Root $preparedStateFileName
}

function Write-PreparedRuntimeState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [psobject]$Snapshot
    )

    $statePath = Get-PreparedStatePath -Root $Root
    $temporaryPath = "$statePath.tmp.$([guid]::NewGuid().ToString('N'))"
    $json = $Snapshot | ConvertTo-Json -Depth 3
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, $encoding)
        Move-Item -LiteralPath $temporaryPath -Destination $statePath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Assert-PreparedRuntimeState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Git,
        [Parameter(Mandatory = $true)]
        [string]$Uv
    )

    $statePath = Get-PreparedStatePath -Root $Root
    $hint = "Run 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 -Checkout . -Prepare'."
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "Prepared runtime state is missing. $hint"
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Prepared runtime state is invalid; run Prepare again. $hint"
    }
    if ($null -eq $state -or $state -is [array]) {
        throw "Prepared runtime state is invalid; run Prepare again. $hint"
    }

    $expectedFields = @(
        "schema_version",
        "git_head",
        "backend_pyproject_sha256",
        "backend_uv_lock_sha256",
        "backend_environment_sha256",
        "backend_environment_packages_sha256",
        "frontend_build_inputs_sha256",
        "frontend_dependency_tree_sha256",
        "frontend_dist_sha256"
    )
    $actualFields = @($state.PSObject.Properties.Name)
    foreach ($field in $actualFields) {
        if ($expectedFields -notcontains $field) {
            throw "Prepared runtime state contains an unknown field; run Prepare again. $hint"
        }
    }
    foreach ($field in $expectedFields) {
        if ($null -eq $state.PSObject.Properties[$field]) {
            throw "Prepared runtime state is incomplete; run Prepare again. $hint"
        }
    }

    try {
        $snapshot = Get-PreparedRuntimeSnapshot -Root $Root -Git $Git -Uv $Uv
    }
    catch {
        throw "Prepared runtime state is stale or incompatible: $($_.Exception.Message) $hint"
    }

    foreach ($field in $expectedFields) {
        $expected = [string]$snapshot.PSObject.Properties[$field].Value
        $actual = [string]$state.PSObject.Properties[$field].Value
        if ($actual -ine $expected) {
            throw "Prepared runtime state is stale or incompatible ($field changed). $hint"
        }
    }
}

try {
    $resolvedCheckout = [IO.Path]::GetFullPath($Checkout)
    if (-not (Test-Path -LiteralPath $resolvedCheckout -PathType Container)) {
        throw "Checkout does not exist: $resolvedCheckout"
    }

    $git = Get-RequiredCommand -Name "git" -InstallHint "Install Git for Windows and ensure git.exe is on PATH."
    $uv = Get-RequiredCommand -Name "uv" -InstallHint "Install uv from https://docs.astral.sh/uv/."
    if ($Validate) {
        Assert-PreparedRuntimeState -Root $resolvedCheckout -Git $git -Uv $uv
        Write-Output "runtime=prepared"
        exit 0
    }

    $powerShell = Get-RequiredCommand -Name "powershell.exe" -InstallHint "Windows PowerShell is required to prepare this runtime."
    $dependencyScript = Join-Path $resolvedCheckout "scripts\prepare-runtime-dependencies.ps1"
    if (-not (Test-Path -LiteralPath $dependencyScript -PathType Leaf)) {
        throw "Dependency preparation helper is missing: $dependencyScript"
    }

    Assert-DependencyMetadata -Root $resolvedCheckout
    $null = Get-GitState -Root $resolvedCheckout -Git $git

    Write-Host "Preparing locked runtime dependencies (-Prepare)..." -ForegroundColor Cyan
    $dependencyResult = Invoke-ChildPowerShell `
        -PowerShell $powerShell `
        -Script $dependencyScript `
        -ArgumentList @("-Checkout", $resolvedCheckout, "-Prepare")
    if (-not [string]::IsNullOrWhiteSpace($dependencyResult.Output)) {
        Write-Host $dependencyResult.Output.TrimEnd()
    }
    if ($dependencyResult.ExitCode -ne 0) {
        throw "Locked dependency preparation failed with exit code $($dependencyResult.ExitCode)."
    }

    $npm = Get-RequiredCommand -Name "npm.cmd" -InstallHint "Install Node.js 22.22 or newer from https://nodejs.org/."
    $backendEnvironmentMarker = Join-Path $resolvedCheckout "backend\.venv\pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $backendEnvironmentMarker -PathType Leaf)) {
        Write-Host "Backend environment marker is missing; restoring the locked backend environment..." -ForegroundColor Cyan
        Push-Location (Join-Path $resolvedCheckout "backend")
        try {
            & $uv sync --locked
            if ($LASTEXITCODE -ne 0) {
                throw "Backend dependency preparation failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }

    $frontendDependencyMarker = Join-Path $resolvedCheckout "frontend\node_modules\.package-lock.json"
    if (-not (Test-Path -LiteralPath $frontendDependencyMarker -PathType Leaf)) {
        Write-Host "Frontend dependency marker is missing; restoring the locked frontend environment..." -ForegroundColor Cyan
        Push-Location (Join-Path $resolvedCheckout "frontend")
        try {
            & $npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend dependency preparation failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }

    Assert-BuildMetadata -Root $resolvedCheckout
    Write-Host "Building frontend production bundle..." -ForegroundColor Cyan
    Push-Location (Join-Path $resolvedCheckout "frontend")
    try {
        & $npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend production build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    $snapshot = Get-PreparedRuntimeSnapshot -Root $resolvedCheckout -Git $git -Uv $uv
    Write-PreparedRuntimeState -Root $resolvedCheckout -Snapshot $snapshot
    Write-Output "runtime=prepared"
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
