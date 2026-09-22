[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RecoveryCheckout,
    [string]$RecoveryPoint,
    [string]$RecoverySha,
    [string]$ControlCheckout,
    [string]$RuntimeConfig,
    [string]$TargetProfile,
    [string]$TargetData,
    [string]$TargetDatabase,
    [string]$ProtectionState,
    [string]$ProtectionMode,
    [switch]$BootstrapOnly,
    [switch]$OwnedBootstrap,
    [ValidateRange(1, 3600)]
    [int]$BootstrapTimeoutSeconds = 1800,
    [switch]$TestForceBootstrapCleanupFailure
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "recovery-bootstrap-safety.ps1")

function Write-PrivacySafeFailure {
    param([string]$Stage = "bootstrap")

    $payload = [ordered]@{
        status = "action_required"
        failure_stage = $Stage
        action_required = "isolated recovery rehearsal was not completed; use a new target after resolving the failure"
    }
    Write-Output ($payload | ConvertTo-Json -Compress)
}

function Assert-NoReparseComponents {
    param([Parameter(Mandatory = $true)][string]$Path)

    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Recovery bootstrap path contains a linked component."
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) {
            break
        }
        $next = $parent.FullName
        if ([string]::Equals($next, $current, [StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $current = $next
    }
}

function Assert-SafeMutableBoundary {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Directory
    )

    Assert-NoReparseComponents -Path $Path
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $root = Get-Item -LiteralPath $Path -Force
    if (($root.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Recovery bootstrap output boundary is linked."
    }
    if ($Directory -and -not $root.PSIsContainer) {
        throw "Recovery bootstrap output boundary has the wrong type."
    }
    if (-not $Directory -and $root.PSIsContainer) {
        throw "Recovery bootstrap output boundary has the wrong type."
    }
    if (-not $Directory) {
        if ((Get-HermesRecoveryLinkCount -Path $root.FullName) -ne 1) {
            throw "Recovery bootstrap output file is hardlinked."
        }
        return
    }

    $pending = New-Object System.Collections.Generic.Queue[string]
    $pending.Enqueue($root.FullName)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($child in @(Get-ChildItem -LiteralPath $current -Force)) {
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Recovery bootstrap output tree contains a linked object."
            }
            if ($child.PSIsContainer) {
                $pending.Enqueue($child.FullName)
            }
            elseif ((Get-HermesRecoveryLinkCount -Path $child.FullName) -ne 1) {
                throw "Recovery bootstrap output tree contains a hardlinked file."
            }
        }
    }
}

function Test-HermesPathOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftPath = [IO.Path]::GetFullPath($Left).TrimEnd('\', '/')
    $rightPath = [IO.Path]::GetFullPath($Right).TrimEnd('\', '/')
    if ([string]::Equals($leftPath, $rightPath, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $separator = [IO.Path]::DirectorySeparatorChar
    return (
        $leftPath.StartsWith($rightPath + $separator, [StringComparison]::OrdinalIgnoreCase) -or
        $rightPath.StartsWith($leftPath + $separator, [StringComparison]::OrdinalIgnoreCase)
    )
}

function Invoke-HermesBootstrapGit {
    param(
        [Parameter(Mandatory = $true)][string]$Checkout,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Push-Location $Checkout
    try {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = & git @Arguments 2>$null | Out-String
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
    }
    finally {
        Pop-Location
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output.Trim()
    }
}

function Get-HermesBootstrapGitValue {
    param(
        [Parameter(Mandatory = $true)][string]$Checkout,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $result = Invoke-HermesBootstrapGit -Checkout $Checkout -Arguments $Arguments
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Output)) {
        throw "Recovery bootstrap Git identity is unavailable."
    }
    return $result.Output
}

function ConvertTo-HermesRemoteKey {
    param([Parameter(Mandatory = $true)][string]$Value)

    $key = $Value.Trim().Replace('\', '/').ToLowerInvariant()
    if ($key.EndsWith('.git')) {
        $key = $key.Substring(0, $key.Length - 4)
    }
    return $key.TrimEnd('/')
}

function Resolve-HermesGitPath {
    param(
        [Parameter(Mandatory = $true)][string]$Checkout,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if ([IO.Path]::IsPathRooted($Value)) {
        return [IO.Path]::GetFullPath($Value)
    }
    return [IO.Path]::GetFullPath((Join-Path $Checkout $Value))
}

function Get-HermesRuntimeBoundaries {
    param([Parameter(Mandatory = $true)][string]$RuntimeConfig)

    Assert-NoReparseComponents -Path $RuntimeConfig
    if (-not (Test-Path -LiteralPath $RuntimeConfig -PathType Leaf)) {
        throw "Recovery runtime inventory is unavailable."
    }
    try {
        $document = Get-Content -LiteralPath $RuntimeConfig -Raw | ConvertFrom-Json
    }
    catch {
        throw "Recovery runtime inventory is invalid."
    }
    if ($null -eq $document -or [int]$document.version -ne 1) {
        throw "Recovery runtime inventory is invalid."
    }
    $canonical = $document.canonical_production
    $profiles = @($document.profiles)
    if ($null -eq $canonical -or $profiles.Count -eq 0) {
        throw "Recovery runtime inventory is invalid."
    }
    $stableProfiles = @($profiles | Where-Object { $_.type -eq 'stable' })
    if ($stableProfiles.Count -ne 1) {
        throw "Recovery runtime inventory is invalid."
    }
    foreach ($profile in $profiles) {
        if ($profile.type -notin @('stable', 'preview', 'experiment')) {
            throw "Recovery runtime inventory is invalid."
        }
    }
    $boundaries = New-Object System.Collections.Generic.List[string]
    foreach ($item in @($canonical) + $profiles) {
        foreach ($name in @('checkout', 'data_dir', 'database')) {
            $value = [string]$item.$name
            if ([string]::IsNullOrWhiteSpace($value) -or -not [IO.Path]::IsPathRooted($value)) {
                throw "Recovery runtime inventory is incomplete."
            }
            $boundaries.Add([IO.Path]::GetFullPath($value))
        }
    }
    foreach ($name in @('checkout', 'data_dir', 'database')) {
        $canonicalValue = [IO.Path]::GetFullPath([string]$canonical.$name)
        $stableValue = [IO.Path]::GetFullPath([string]$stableProfiles[0].$name)
        if (-not [string]::Equals(
            $canonicalValue,
            $stableValue,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Recovery Stable inventory is not canonical."
        }
    }
    return $boundaries.ToArray()
}

function Assert-HermesRecoveryBootstrapPreflight {
    param(
        [Parameter(Mandatory = $true)][string]$Checkout,
        [Parameter(Mandatory = $true)][string]$SelectedSha,
        [Parameter(Mandatory = $true)][string]$ControlCheckout,
        [Parameter(Mandatory = $true)][string]$RuntimeConfig
    )

    if ($SelectedSha -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Recovery SHA is invalid."
    }
    $control = [IO.Path]::GetFullPath($ControlCheckout).TrimEnd('\', '/')
    if (-not (Test-Path -LiteralPath $Checkout -PathType Container) -or
        -not (Test-Path -LiteralPath $control -PathType Container) -or
        (Test-HermesPathOverlap -Left $Checkout -Right $control)) {
        throw "Recovery and control checkouts are not independent."
    }
    Assert-NoReparseComponents -Path $Checkout
    Assert-NoReparseComponents -Path $control
    $recoveryTop = Get-HermesBootstrapGitValue -Checkout $Checkout -Arguments @(
        'rev-parse', '--show-toplevel'
    )
    $controlTop = Get-HermesBootstrapGitValue -Checkout $control -Arguments @(
        'rev-parse', '--show-toplevel'
    )
    if (-not [string]::Equals(
        [IO.Path]::GetFullPath($recoveryTop).TrimEnd('\', '/'),
        $Checkout,
        [StringComparison]::OrdinalIgnoreCase
    ) -or -not [string]::Equals(
        [IO.Path]::GetFullPath($controlTop).TrimEnd('\', '/'),
        $control,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Recovery bootstrap Git toplevel is invalid."
    }
    $head = Get-HermesBootstrapGitValue -Checkout $Checkout -Arguments @(
        'rev-parse', '--verify', 'HEAD^{commit}'
    )
    if (-not [string]::Equals($head, $SelectedSha, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery bootstrap is not pinned to the selected SHA."
    }
    $symbolic = Invoke-HermesBootstrapGit -Checkout $Checkout -Arguments @(
        'symbolic-ref', '--quiet', '--short', 'HEAD'
    )
    if ($symbolic.ExitCode -eq 0 -or -not [string]::IsNullOrWhiteSpace($symbolic.Output)) {
        throw "Recovery bootstrap checkout is not detached."
    }
    foreach ($gitArguments in @(
        @('status', '--porcelain=v1', '--untracked-files=all'),
        @('ls-files', '-u')
    )) {
        $result = Invoke-HermesBootstrapGit -Checkout $Checkout -Arguments $gitArguments
        if ($result.ExitCode -ne 0 -or -not [string]::IsNullOrWhiteSpace($result.Output)) {
            throw "Recovery bootstrap checkout is not clean."
        }
    }
    $gitDirectory = Resolve-HermesGitPath -Checkout $Checkout -Value (
        Get-HermesBootstrapGitValue -Checkout $Checkout -Arguments @('rev-parse', '--git-dir')
    )
    $commonDirectory = Resolve-HermesGitPath -Checkout $Checkout -Value (
        Get-HermesBootstrapGitValue -Checkout $Checkout -Arguments @(
            'rev-parse', '--git-common-dir'
        )
    )
    if (-not (Test-Path -LiteralPath (Join-Path $Checkout '.git') -PathType Container) -or
        -not (Test-HermesPathOverlap -Left $gitDirectory -Right $Checkout) -or
        -not (Test-HermesPathOverlap -Left $commonDirectory -Right $Checkout)) {
        throw "Recovery bootstrap Git metadata is not independent."
    }
    $recoveryRemote = Get-HermesBootstrapGitValue -Checkout $Checkout -Arguments @(
        'remote', 'get-url', 'origin'
    )
    $controlRemote = Get-HermesBootstrapGitValue -Checkout $control -Arguments @(
        'remote', 'get-url', 'origin'
    )
    if ((ConvertTo-HermesRemoteKey -Value $recoveryRemote) -ne
        (ConvertTo-HermesRemoteKey -Value $controlRemote)) {
        throw "Recovery bootstrap repository identity is invalid."
    }
    if ((Test-Path -LiteralPath (Join-Path $Checkout '.env')) -or
        (Test-Path -LiteralPath (Join-Path $Checkout 'private'))) {
        throw "Recovery bootstrap checkout contains a private runtime boundary."
    }
    $data = Join-Path $Checkout 'data'
    if (Test-Path -LiteralPath $data -PathType Container) {
        $unexpected = @(Get-ChildItem -LiteralPath $data -Force | Where-Object { $_.Name -ne '.gitkeep' })
        if ($unexpected.Count -ne 0) {
            throw "Recovery bootstrap checkout contains runtime data."
        }
    }

    $forbidden = New-Object System.Collections.Generic.List[string]
    foreach ($boundary in @(Get-HermesRuntimeBoundaries -RuntimeConfig $RuntimeConfig)) {
        $forbidden.Add($boundary)
    }
    $worktrees = Get-HermesBootstrapGitValue -Checkout $control -Arguments @(
        'worktree', 'list', '--porcelain'
    )
    foreach ($line in @($worktrees -split "`r?`n")) {
        if ($line.StartsWith('worktree ')) {
            $forbidden.Add([IO.Path]::GetFullPath($line.Substring(9)))
        }
    }
    if ($forbidden.Count -eq 0) {
        throw "Recovery bootstrap forbidden inventory is unavailable."
    }
    foreach ($boundary in $forbidden) {
        if (Test-HermesPathOverlap -Left $Checkout -Right $boundary) {
            throw "Recovery bootstrap checkout is forbidden."
        }
    }
}

function Enter-HermesRecoveryPrepareContainment {
    param([Parameter(Mandatory = $true)][string]$Checkout)

    $directoryBoundaries = @(
        (Join-Path $Checkout 'backend\.venv'),
        (Join-Path $Checkout 'frontend\node_modules'),
        (Join-Path $Checkout 'frontend\dist'),
        (Join-Path $Checkout '.tmp')
    )
    $fileBoundary = Join-Path $Checkout '.hermes-runtime-prepared.json'
    foreach ($path in $directoryBoundaries) {
        Assert-SafeMutableBoundary -Path $path -Directory $true
    }
    Assert-SafeMutableBoundary -Path $fileBoundary -Directory $false
    $guards = New-Object System.Collections.Generic.List[object]
    try {
        foreach ($path in $directoryBoundaries) {
            if (-not (Test-Path -LiteralPath $path)) {
                New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
            }
            Assert-SafeMutableBoundary -Path $path -Directory $true
            $guards.Add((Open-HermesRecoveryDirectoryGuard -Path $path))
        }
        return $guards.ToArray()
    }
    catch {
        foreach ($guard in $guards) {
            $guard.Dispose()
        }
        throw
    }
}

if (-not $OwnedBootstrap) {
    $arguments = @(
        '-RecoveryCheckout', $RecoveryCheckout,
        '-RecoveryPoint', $RecoveryPoint,
        '-RecoverySha', $RecoverySha,
        '-ControlCheckout', $ControlCheckout,
        '-RuntimeConfig', $RuntimeConfig,
        '-TargetProfile', $TargetProfile,
        '-TargetData', $TargetData,
        '-TargetDatabase', $TargetDatabase,
        '-ProtectionState', $ProtectionState,
        '-ProtectionMode', $ProtectionMode,
        '-OwnedBootstrap'
    )
    if ($BootstrapOnly) {
        $arguments += '-BootstrapOnly'
    }
    try {
        $result = Invoke-HermesOwnedRecoveryBootstrap `
            -BoundaryScript (Join-Path $PSScriptRoot 'recovery-bootstrap-boundary.ps1') `
            -RecoveryScript $PSCommandPath `
            -Arguments $arguments `
            -TimeoutSeconds $BootstrapTimeoutSeconds `
            -ForceCleanupFailure:$TestForceBootstrapCleanupFailure
        if (-not [string]::IsNullOrWhiteSpace($result.StandardOutput)) {
            Write-Output $result.StandardOutput.Trim()
        }
        exit $result.ExitCode
    }
    catch {
        $stage = if ($_.Exception.Message -eq 'bootstrap-cleanup') {
            'bootstrap-cleanup'
        }
        elseif ($_.Exception.Message -eq 'bootstrap-timeout') {
            'bootstrap-timeout'
        }
        else {
            'bootstrap'
        }
        Write-PrivacySafeFailure -Stage $stage
        exit 2
    }
}

$guards = @()
try {
    if (
        $env:HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN -notmatch '^[0-9a-f]{64}$' -or
        -not [HermesRecoveryBootstrapNative]::IsCurrentProcessOwned(
            $env:HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN
        )
    ) {
        throw "Recovery bootstrap ownership is unavailable."
    }
    $checkout = [IO.Path]::GetFullPath($RecoveryCheckout).TrimEnd('\', '/')
    $scriptCheckout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
    if (-not [string]::Equals($checkout, $scriptCheckout, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery bootstrap must execute from the selected checkout."
    }
    foreach ($value in @(
        $RecoveryPoint,
        $RecoverySha,
        $ControlCheckout,
        $RuntimeConfig,
        $TargetProfile,
        $TargetData,
        $TargetDatabase,
        $ProtectionState,
        $ProtectionMode
    )) {
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Recovery bootstrap arguments are incomplete."
        }
    }
    $backend = Join-Path $checkout 'backend'
    $frontend = Join-Path $checkout 'frontend'
    foreach ($required in @(
        (Join-Path $backend 'pyproject.toml'),
        (Join-Path $backend 'uv.lock'),
        (Join-Path $frontend 'package.json'),
        (Join-Path $frontend 'package-lock.json'),
        (Join-Path $checkout 'scripts\recovery-bootstrap-boundary.ps1'),
        (Join-Path $checkout 'scripts\recovery-bootstrap-safety.ps1')
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Recovery bootstrap checkout is incomplete."
        }
    }
    Assert-HermesRecoveryBootstrapPreflight `
        -Checkout $checkout `
        -SelectedSha $RecoverySha `
        -ControlCheckout $ControlCheckout `
        -RuntimeConfig $RuntimeConfig
    $guards = @(Enter-HermesRecoveryPrepareContainment -Checkout $checkout)

    if ($BootstrapOnly) {
        foreach ($guard in $guards) {
            $guard.AssertDirectoryIdentity($guard.Path)
        }
        Write-Output '{"status":"bootstrap_verified"}'
        exit 0
    }

    $uvCommand = Get-Command 'uv' -ErrorAction Stop
    $savedEnvironment = @{}
    foreach ($name in @(
        'UV_PROJECT_ENVIRONMENT',
        'UV_PROJECT',
        'UV_WORKING_DIR',
        'UV_LINK_MODE',
        'VIRTUAL_ENV',
        'TEMP',
        'TMP'
    )) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        $env:UV_PROJECT_ENVIRONMENT = [IO.Path]::GetFullPath((Join-Path $backend '.venv'))
        $env:UV_LINK_MODE = 'copy'
        $env:TEMP = [IO.Path]::GetFullPath((Join-Path $checkout '.tmp'))
        $env:TMP = $env:TEMP
        Remove-Item Env:UV_PROJECT -ErrorAction SilentlyContinue
        Remove-Item Env:UV_WORKING_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $output = & $uvCommand.Source `
                run `
                --project $backend `
                --locked `
                hermes-finance-recovery-rehearsal `
                --recovery-point $RecoveryPoint `
                --recovery-sha $RecoverySha `
                --recovery-checkout $checkout `
                --control-checkout $ControlCheckout `
                --runtime-config $RuntimeConfig `
                --target-profile $TargetProfile `
                --target-data $TargetData `
                --target-database $TargetDatabase `
                --protection-state $ProtectionState `
                --protection-mode $ProtectionMode 2>$null | Out-String
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
    }
    finally {
        foreach ($name in $savedEnvironment.Keys) {
            $value = $savedEnvironment[$name]
            if ($null -eq $value) {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:$name" $value
            }
        }
    }
    foreach ($guard in $guards) {
        $guard.AssertDirectoryIdentity($guard.Path)
    }
    foreach ($path in @(
        (Join-Path $backend '.venv'),
        (Join-Path $frontend 'node_modules'),
        (Join-Path $frontend 'dist'),
        (Join-Path $checkout '.tmp')
    )) {
        Assert-SafeMutableBoundary -Path $path -Directory $true
    }
    Assert-SafeMutableBoundary `
        -Path (Join-Path $checkout '.hermes-runtime-prepared.json') `
        -Directory $false
    if ([string]::IsNullOrWhiteSpace($output)) {
        Write-PrivacySafeFailure
        exit 2
    }
    try {
        $null = $output | ConvertFrom-Json -ErrorAction Stop
        Write-Output $output.Trim()
    }
    catch {
        Write-PrivacySafeFailure
        exit 2
    }
    exit $exitCode
}
catch {
    Write-PrivacySafeFailure
    exit 2
}
finally {
    foreach ($guard in $guards) {
        try { $guard.Dispose() } catch {}
    }
}
