[CmdletBinding()]
param(
    [switch]$ExitAfterReady,
    [switch]$RecoveryReadiness,
    [switch]$ScratchPreflight,
    [string]$ScratchManifest,
    [int]$PreviewPort
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "recovery-runtime-safety.ps1")
. (Join-Path $PSScriptRoot "recovery-readiness.ps1")
. (Join-Path $PSScriptRoot "prepare-preview-lib.ps1")

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$frontendDist = Join-Path $frontendDir "dist"
$backendProcess = $null
$exitCode = 0
$previewRequested = $PSBoundParameters.ContainsKey("PreviewPort")
$selectedPort = 8000
$previewBinding = $null
$previewProcessIdentity = $null

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

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [bool]$RecoveryReadiness = $false,
        [bool]$RequireInspection = $false
    )

    if ($null -eq (Get-Command "Get-NetTCPConnection" -ErrorAction SilentlyContinue)) {
        if ($RequireInspection) { throw "Preview port inspection is unavailable." }
        return
    }

    if ($RequireInspection) {
        try { $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop }
        catch {
            if ($_.FullyQualifiedErrorId -notlike "CmdletizationQuery_NotFound,*") { throw }
            $listener = $null
        }
    }
    else { $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue }
    if ($null -ne $listener) {
        if ($RecoveryReadiness) {
            Throw-HermesRecoveryReadinessFailure -Classification "port_conflict"
        }
        throw "Port $Port is already in use. Stop the existing process before starting Hermes Finance."
    }
}

function Assert-ProcessRunning {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $Process.Refresh()
    if ($Process.HasExited) {
        throw "$Name stopped unexpectedly with exit code $($Process.ExitCode)."
    }
}

function Get-HermesScratchDriveType {
    param([string]$Root)
    return ([IO.DriveInfo]::new($Root)).DriveType
}

function Assert-HermesScratchLocalPathSyntax {
    param([string]$Path)
    # Syntax only: do not Test-Path/Get-Item/resolve an untrusted remote path.
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path.Substring(3).Contains(':') -or $Path.Contains('"') -or
        @($Path -split '[\\/]' | Where-Object { $_ -eq '..' }).Count -gt 0) {
        throw "Scratch requires an absolute local filesystem path."
    }
    $driveType = Get-HermesScratchDriveType -Root ([IO.Path]::GetPathRoot($Path))
    if ([int]$driveType -notin @(2, 3, 5, 6)) {
        throw "Scratch requires a local available drive."
    }
}

function Assert-HermesScratchPathBoundary {
    param([string]$Path)
    Assert-HermesScratchLocalPathSyntax -Path $Path
    $components = New-Object 'System.Collections.Generic.List[string]'
    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $components.Add($current)
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
    $components.Reverse()
    foreach ($component in $components) {
        # Get-Item on this component inspects the reparse entry itself. Do not
        # Test-Path/probe a descendant until every ancestor has been inspected.
        $item = Get-Item -LiteralPath $component -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Scratch path contains a reparse boundary."
        }
    }
}

function Assert-HermesScratchInterpreterBoundary {
    param([string]$Checkout)
    $python = Join-Path $Checkout "backend\.venv\Scripts\python.exe"
    Assert-HermesScratchPathBoundary -Path $python
    $item = Get-Item -LiteralPath $python -Force -ErrorAction Stop
    if ($item.PSIsContainer -or $item.LinkType -eq "HardLink") {
        throw "Scratch requires its own unlinked prepared interpreter."
    }
}

function Wait-ForScratchPreflight {
    param($Backend, [string]$Token, $Binding)

    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        Assert-ProcessRunning -Process $Backend -Name "Scratch preflight"
        $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) {
            Start-Sleep -Milliseconds 250
            continue
        }
        $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        if (-not (Test-HermesLoopbackListenerOwnership -RootProcessId $Backend.Id -Listeners $listeners -ProcessRows $rows)) {
            Start-Sleep -Milliseconds 250
            continue
        }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 2
        }
        catch {
            Start-Sleep -Milliseconds 250
            continue
        }
        if (-not (Test-HermesRecoveryHeaders -Response $response -ExpectedToken $Token -ExpectedDatabaseIdentity $Binding.database_identity -ExpectedCheckoutSha $Binding.checkout_sha)) {
            throw "Scratch process identity mismatch."
        }
        $health = $response.Content | ConvertFrom-Json
        $listener = @($listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" -and $_.LocalPort -eq 8000 })
        $process = @($rows | Where-Object { $_.ProcessId -eq $health.pid })
        if ($health.mode -ne "mybroker_preflight_scratch" -or $health.pid -ne $listener[0].OwningProcess -or
            $process.Count -ne 1 -or $null -eq $process[0].CreationDate -or
            [string]::IsNullOrWhiteSpace($process[0].ExecutablePath)) {
            throw "Scratch listener/process binding is unavailable."
        }
        return
    }
    throw "Scratch readiness timed out."
}

function Invoke-PreparedRuntimeValidation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PowerShell,
        [Parameter(Mandatory = $true)]
        [string]$Checkout
    )

    $preparedStateScript = Join-Path $Checkout "scripts\prepare-runtime.ps1"
    if (-not (Test-Path -LiteralPath $preparedStateScript -PathType Leaf)) {
        throw "Prepared runtime validation is unavailable. Run the explicit Prepare command from a complete Hermes Finance checkout."
    }

    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $PowerShell `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $preparedStateScript `
            -Checkout $Checkout `
            -Validate 2>&1 | Out-String
        $validationExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($validationExitCode -ne 0) {
        $detail = $output.Trim()
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = "Prepared runtime validation failed without a diagnostic."
        }
        throw $detail
    }
}

function Get-HermesStartPort {
    param([bool]$PreviewRequested, [int]$PreviewPort, [bool]$RecoveryReadiness, [bool]$ScratchPreflight, [string]$ScratchManifest)
    if (-not $PreviewRequested) { return 8000 }
    if ($PreviewPort -lt 1024 -or $PreviewPort -gt 65535 -or $PreviewPort -eq 8000) {
        throw "PreviewPort must be an explicit non-default port from 1024 through 65535."
    }
    if ($RecoveryReadiness -or $ScratchPreflight -or -not [string]::IsNullOrWhiteSpace($ScratchManifest)) {
        throw "PreviewPort cannot be combined with recovery or scratch modes."
    }
    return $PreviewPort
}

function Get-HermesPreviewStartBinding {
    param([Parameter(Mandatory = $true)][string]$Checkout)
    Assert-HermesScratchPathBoundary -Path (Join-Path $Checkout ".hermes-preview-boundary.json")
    $pin = Read-HermesPreviewCandidateBoundary -Checkout $Checkout
    foreach ($field in @("ControlCheckout", "StableCheckout", "StableDataDirectory", "StableDatabase", "PreviewCheckout", "PreviewDataDirectory", "PreviewDatabase")) {
        Assert-HermesScratchPathBoundary -Path ([string]$pin.$field)
    }
    Assert-HermesScratchPathBoundary -Path (Join-Path $pin.PreviewDataDirectory ".hermes-data-identity.json")
    Assert-HermesScratchInterpreterBoundary -Checkout $Checkout
    $database = Assert-HermesPreviewPinnedRuntimeBoundary -Checkout $Checkout
    $context = [pscustomobject]@{ GitPath = (Get-RequiredCommand -Name "git" -InstallHint "Git is required for Preview identity."); CommandRunner = New-HermesPreviewCommandRunner }
    Assert-HermesPreviewCleanCheckout -Context $context -Checkout $Checkout -Label "Preview checkout"
    $head = Get-HermesPreviewObservedHead -Context $context -Checkout $Checkout
    Assert-HermesScratchPathBoundary -Path (Join-Path $Checkout ".hermes-runtime-prepared.json")
    $prepared = Get-Content -LiteralPath (Join-Path $Checkout ".hermes-runtime-prepared.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($head -cne $pin.CandidateSha -or $prepared.git_head -cne $pin.CandidateSha) {
        throw "Preview candidate SHA does not match HEAD and prepared proof; repeat exact-candidate OPS03."
    }
    $controlCommon = Get-HermesPreviewGitCommonDirectory -Context $context -Checkout $pin.ControlCheckout
    $stableCommon = Get-HermesPreviewGitCommonDirectory -Context $context -Checkout $pin.StableCheckout
    Assert-HermesPreviewIndependentCheckout -Context $context -PreviewCheckout $Checkout -ControlCommonDirectory $controlCommon -StableCommonDirectory $stableCommon | Out-Null
    # Only stat/file identity through the prepared interpreter: no app import,
    # SQLite connection, migration, configuration output or dependency sync.
    $result = Invoke-HermesPreviewExternalCommand -Context $context -Name "preview-file-identity" `
        -FilePath (Join-Path $Checkout "backend\.venv\Scripts\python.exe") -WorkingDirectory (Join-Path $Checkout "backend") `
        -ArgumentList @("-I", "-c", "import sys; sys.path.insert(0, 'src'); from pathlib import Path; from hermes_finance.services.recovery_process import file_identity_token; print(file_identity_token(Path(sys.argv[1])))", $database) -AllowFailure
    $identity = ([string]$result.Stdout).Trim()
    if ($result.ExitCode -ne 0 -or $identity -cnotmatch '^[0-9a-f]{64}$') { throw "Preview database file identity is unavailable." }
    return [pscustomobject]@{ Database = $database; DatabaseIdentity = $identity; CheckoutSha = $head; Token = ([Guid]::NewGuid().ToString("N") + [Guid]::NewGuid().ToString("N")) }
}

function Get-HermesPreviewProcessIdentity {
    param([System.Diagnostics.Process]$Backend)
    Assert-ProcessRunning -Process $Backend -Name "Preview backend"
    $rows = @(Get-CimInstance Win32_Process -Filter ("ProcessId=" + $Backend.Id) -ErrorAction Stop)
    if ($rows.Count -ne 1 -or $null -eq $rows[0].CreationDate -or [string]::IsNullOrWhiteSpace($rows[0].ExecutablePath) -or
        [Math]::Abs($rows[0].CreationDate.ToUniversalTime().Ticks - $Backend.StartTime.ToUniversalTime().Ticks) -gt 10) {
        throw "Preview process creation identity is unavailable."
    }
    Assert-ProcessRunning -Process $Backend -Name "Preview backend"
    return [pscustomobject]@{ ProcessId = $Backend.Id; CreationTicks = $rows[0].CreationDate.ToUniversalTime().Ticks; ExecutablePath = $rows[0].ExecutablePath }
}

function Test-HermesPreviewListener {
    param([System.Diagnostics.Process]$Backend, $Identity, [int]$Port)
    Assert-ProcessRunning -Process $Backend -Name "Preview backend"
    $current = Get-HermesPreviewProcessIdentity -Backend $Backend
    if ($current.CreationTicks -ne $Identity.CreationTicks -or $current.ProcessId -ne $Identity.ProcessId -or $current.ExecutablePath -ine $Identity.ExecutablePath) {
        throw "Preview process identity changed."
    }
    try { $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop) }
    catch {
        if ($_.FullyQualifiedErrorId -notlike "CmdletizationQuery_NotFound,*") { throw }
        $listeners = @()
    }
    if ($listeners.Count -eq 0) { return $false }
    $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    if (-not (Test-HermesPreviewListenerOwnership -RootProcessId $Backend.Id -RootCreationTicks $Identity.CreationTicks -RootExecutablePath $Identity.ExecutablePath -Port $Port -Listeners $listeners -ProcessRows $rows)) {
        throw "Preview listener is foreign or its current creation ancestry cannot be proven."
    }
    return $true
}

function Wait-ForPreviewStack {
    param([System.Diagnostics.Process]$Backend, $Identity, $Binding, [int]$Port)
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Test-HermesPreviewListener -Backend $Backend -Identity $Identity -Port $Port)) { Start-Sleep -Milliseconds 250; continue }
        $ready = $true
        foreach ($path in @("/api/health", "/api/months", "/")) {
            try { $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}{1}" -f $Port, $path) -UseBasicParsing -TimeoutSec 2 }
            catch {
                if (Test-HermesRecoveryTransientRequestFailure -Exception $_.Exception) { $ready = $false; break }
                throw
            }
            if (-not (Test-HermesPreviewListener -Backend $Backend -Identity $Identity -Port $Port) -or
                -not (Test-HermesRecoveryHeaders -Response $response -ExpectedToken $Binding.Token -ExpectedDatabaseIdentity $Binding.DatabaseIdentity -ExpectedCheckoutSha $Binding.CheckoutSha)) {
                throw "Preview readiness identity mismatch."
            }
            if ($response.StatusCode -ne 200 -or ($path -eq "/" -and $response.Content -notmatch "Hermes Finance")) { throw "Preview readiness surface is unavailable." }
        }
        if ($ready) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Preview readiness timed out."
}

function Wait-ForProductionStack {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Backend,
        [Parameter(Mandatory = $true)]
        [bool]$RequireRecoverySurfaces,
        [string]$ExpectedRecoveryToken,
        [string]$ExpectedDatabaseIdentity,
        [string]$ExpectedCheckoutSha
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $lastFailureReason = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            Assert-ProcessRunning -Process $Backend -Name "Backend"
        }
        catch {
            if ($RequireRecoverySurfaces) {
                Throw-HermesRecoveryReadinessFailure -Classification "backend_exit"
            }
            throw
        }

        try {
            if ($RequireRecoverySurfaces -and -not (Test-RecoveryListenerOwned -Backend $Backend)) {
                $lastFailureReason = "listener_not_owned"
                Start-Sleep -Milliseconds 250
                continue
            }
            $health = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/api/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($RequireRecoverySurfaces) {
                $ownershipFailure = Get-HermesRecoveryResponseFailureClassification -Backend $Backend -Response $health -ExpectedRecoveryToken $ExpectedRecoveryToken -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity -ExpectedCheckoutSha $ExpectedCheckoutSha
                if ($null -ne $ownershipFailure) {
                    Throw-HermesRecoveryReadinessFailure -Classification $ownershipFailure
                }
            }
            $months = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/api/months" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($RequireRecoverySurfaces) {
                $ownershipFailure = Get-HermesRecoveryResponseFailureClassification -Backend $Backend -Response $months -ExpectedRecoveryToken $ExpectedRecoveryToken -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity -ExpectedCheckoutSha $ExpectedCheckoutSha
                if ($null -ne $ownershipFailure) {
                    Throw-HermesRecoveryReadinessFailure -Classification $ownershipFailure
                }
            }
            $frontend = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($RequireRecoverySurfaces) {
                $ownershipFailure = Get-HermesRecoveryResponseFailureClassification -Backend $Backend -Response $frontend -ExpectedRecoveryToken $ExpectedRecoveryToken -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity -ExpectedCheckoutSha $ExpectedCheckoutSha
                if ($null -ne $ownershipFailure) {
                    Throw-HermesRecoveryReadinessFailure -Classification $ownershipFailure
                }
            }
            $baseReady = (
                $health.StatusCode -eq 200 -and
                $months.StatusCode -eq 200 -and
                $frontend.StatusCode -eq 200 -and
                $frontend.Content -match "Hermes Finance"
            )
            if (
                $RequireRecoverySurfaces -and
                ($health.StatusCode -ne 200 -or $months.StatusCode -ne 200 -or $frontend.StatusCode -ne 200)
            ) {
                Throw-HermesRecoveryReadinessFailure -Classification "api_http_status"
            }
            if ($RequireRecoverySurfaces -and $frontend.Content -notmatch "Hermes Finance") {
                Throw-HermesRecoveryReadinessFailure -Classification "readiness_probe_defect"
            }
            if ($baseReady -and -not $RequireRecoverySurfaces) {
                return
            }
            if ($baseReady) {
                $accounts = Invoke-WebRequest `
                    -Uri "http://127.0.0.1:8000/api/accounts" `
                    -UseBasicParsing `
                    -TimeoutSec 2
                if ($accounts.StatusCode -ne 200) {
                    Throw-HermesRecoveryReadinessFailure -Classification "api_http_status"
                }
                $ownershipFailure = Get-HermesRecoveryResponseFailureClassification -Backend $Backend -Response $accounts -ExpectedRecoveryToken $ExpectedRecoveryToken -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity -ExpectedCheckoutSha $ExpectedCheckoutSha
                if ($null -ne $ownershipFailure) {
                    Throw-HermesRecoveryReadinessFailure -Classification $ownershipFailure
                }

                $null = Invoke-HermesRecoveryDashboardProbe `
                    -MonthsJson ([string]$months.Content) `
                    -Backend $Backend `
                    -ExpectedRecoveryToken $ExpectedRecoveryToken `
                    -ExpectedDatabaseIdentity $ExpectedDatabaseIdentity `
                    -ExpectedCheckoutSha $ExpectedCheckoutSha
                return
            }
        }
        catch {
            if ($RequireRecoverySurfaces) {
                $classification = Get-HermesRecoveryReadinessClassification -ErrorRecord $_
                if ($null -ne $classification) {
                    throw
                }
                if ($null -ne (Get-HermesRecoveryHttpStatusCode -Exception $_.Exception)) {
                    Throw-HermesRecoveryReadinessFailure -Classification "api_http_status"
                }
                elseif (Test-HermesRecoveryTransientRequestFailure -Exception $_.Exception) {
                    $lastFailureReason = "startup_http_unavailable"
                }
                else {
                    Throw-HermesRecoveryReadinessFailure -Classification "readiness_probe_defect"
                }
            }
            # In recovery mode only startup network failures and non-ready HTTP statuses retry.
        }

        Start-Sleep -Milliseconds 250
    }

    if ($RequireRecoverySurfaces) {
        if ([string]::IsNullOrWhiteSpace($lastFailureReason)) {
            $lastFailureReason = "readiness_timeout"
        }
        Throw-HermesRecoveryReadinessFailure -Classification $lastFailureReason
    }
    throw "Production stack did not become ready within 45 seconds."
}

function Stop-ProcessTree {
    param(
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($null -eq $Process) {
        return
    }

    $Process.Refresh()
    if ($Process.HasExited) {
        return
    }

    Write-Host "Stopping $Name..." -ForegroundColor DarkGray
    $taskKill = Start-Process `
        -FilePath (Join-Path $env:SystemRoot "System32\taskkill.exe") `
        -ArgumentList @("/PID", $Process.Id, "/T", "/F") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($taskKill.ExitCode -ne 0) {
        throw "Failed to stop $Name process tree (PID $($Process.Id))."
    }
}

try {
    $selectedPort = Get-HermesStartPort -PreviewRequested $previewRequested -PreviewPort $PreviewPort -RecoveryReadiness ([bool]$RecoveryReadiness) -ScratchPreflight ([bool]$ScratchPreflight) -ScratchManifest $ScratchManifest
    if ($previewRequested) {
        foreach ($command in @("Get-NetTCPConnection", "Get-CimInstance")) {
            if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Preview process ownership checks are unavailable." }
        }
        foreach ($name in @("HERMES_FINANCE_RECOVERY_READINESS_TOKEN", "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY", "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA")) {
            if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) { throw "PreviewPort cannot inherit recovery readiness identity." }
        }
    }
    if ($ScratchPreflight -or -not [string]::IsNullOrWhiteSpace($ScratchManifest)) {
        if (-not $ScratchPreflight -or [string]::IsNullOrWhiteSpace($ScratchManifest) -or $RecoveryReadiness) {
            throw "Scratch preflight requires its explicit manifest and cannot use recovery readiness."
        }
        foreach ($command in @("Get-NetTCPConnection", "Get-CimInstance")) {
            if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) {
                throw "Scratch process ownership checks are unavailable."
            }
        }
        Assert-HermesScratchLocalPathSyntax -Path $ScratchManifest
        Assert-HermesScratchPathBoundary -Path $ScratchManifest
        Assert-HermesScratchInterpreterBoundary -Checkout $repoRoot
    }
    if ($RecoveryReadiness -and -not $ExitAfterReady) {
        throw "Recovery readiness is a bounded smoke and requires -ExitAfterReady."
    }
    if ($RecoveryReadiness) {
        foreach ($requiredCommand in @("Get-NetTCPConnection", "Get-CimInstance")) {
            if ($null -eq (Get-Command $requiredCommand -ErrorAction SilentlyContinue)) {
                throw "Recovery readiness process ownership checks are unavailable."
            }
        }
        if (
            $env:HERMES_FINANCE_RECOVERY_READINESS_TOKEN -notmatch "^[0-9a-f]{64}$" -or
            $env:HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY -notmatch "^[0-9a-f]{64}$" -or
            $env:HERMES_FINANCE_RECOVERY_CHECKOUT_SHA -notmatch "^[0-9a-f]{40}$"
        ) {
            throw "Recovery readiness identity is missing or invalid."
        }
        $expectedProjectEnvironment = [IO.Path]::GetFullPath((Join-Path $backendDir ".venv"))
        $actualProjectEnvironment = [IO.Path]::GetFullPath($env:UV_PROJECT_ENVIRONMENT)
        if (-not [string]::Equals(
            $actualProjectEnvironment,
            $expectedProjectEnvironment,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Recovery runtime environment is not isolated to the selected checkout."
        }
    }
    $uv = Get-RequiredCommand -Name "uv" -InstallHint "Install uv from https://docs.astral.sh/uv/."
    $powershell = Get-RequiredCommand -Name "powershell.exe" -InstallHint "Windows PowerShell is required to validate the prepared runtime."

    if (-not (Test-Path (Join-Path $backendDir "pyproject.toml") -PathType Leaf)) {
        throw "Backend project not found at '$backendDir'. Run this script from the Hermes Finance repository."
    }
    if (-not (Test-Path (Join-Path $frontendDir "package.json") -PathType Leaf)) {
        throw "Frontend project not found at '$frontendDir'. Run this script from the Hermes Finance repository."
    }

    Invoke-PreparedRuntimeValidation -PowerShell $powershell -Checkout $repoRoot

    if ($previewRequested) { $previewBinding = Get-HermesPreviewStartBinding -Checkout $repoRoot }
    Assert-PortAvailable -Port $selectedPort -RecoveryReadiness ([bool]$RecoveryReadiness) -RequireInspection $previewRequested

    $savedEnvironment = @{}
    foreach ($name in @(
        "HERMES_FINANCE_HOST",
        "HERMES_FINANCE_PORT",
        "HERMES_FINANCE_RELOAD",
        "HERMES_FINANCE_DATABASE_PATH",
        "HERMES_FINANCE_FRONTEND_DIST",
        "HERMES_FINANCE_RECOVERY_READINESS_TOKEN",
        "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY",
        "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA",
        "UV_OFFLINE",
        "UV_PROJECT_ENVIRONMENT",
        "PYTHONPATH"
    )) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        $env:HERMES_FINANCE_HOST = "127.0.0.1"
        $env:HERMES_FINANCE_PORT = [string]$selectedPort
        $env:HERMES_FINANCE_RELOAD = "false"
        $env:HERMES_FINANCE_FRONTEND_DIST = $frontendDist
        $env:UV_OFFLINE = "1"
        $env:UV_PROJECT_ENVIRONMENT = [IO.Path]::GetFullPath((Join-Path $backendDir ".venv"))
        $env:PYTHONPATH = ""

        if ($previewRequested) {
            $env:HERMES_FINANCE_DATABASE_PATH = $previewBinding.Database
            $env:HERMES_FINANCE_RECOVERY_READINESS_TOKEN = $previewBinding.Token
            $env:HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY = $previewBinding.DatabaseIdentity
            $env:HERMES_FINANCE_RECOVERY_CHECKOUT_SHA = $previewBinding.CheckoutSha
        }
        if ($ScratchPreflight) {
            # The backend checks the exact same binding even when called directly.
            # This check serves nothing, creates nothing and cannot run migrations.
            $scratchToken = [Guid]::NewGuid().ToString("N") + [Guid]::NewGuid().ToString("N")
            $scratchBinding = Get-Content -LiteralPath $ScratchManifest -Raw | ConvertFrom-Json
            Assert-HermesScratchInterpreterBoundary -Checkout $repoRoot
            $python = Join-Path $backendDir ".venv\Scripts\python.exe"
            & $python -m hermes_finance.scratch_preflight --manifest $ScratchManifest --readiness-token $scratchToken --check
            if ($LASTEXITCODE -ne 0) { throw "Scratch validation failed." }
            $backendArguments = @("run", "--locked", "--offline", "--no-sync", "hermes-finance-api", "scratch-preflight",
                "--manifest", ('"' + $ScratchManifest + '"'), "--readiness-token", $scratchToken)
        }
        else {
            $pinnedDatabase = if ($previewRequested) { $previewBinding.Database } else { Assert-HermesPreviewPinnedRuntimeBoundary -Checkout $repoRoot }
            if ($null -ne $pinnedDatabase) {
                $env:HERMES_FINANCE_DATABASE_PATH = $pinnedDatabase
            }
            $backendArguments = @("run", "--locked", "--offline", "--no-sync", "hermes-finance-api")
        }

        if ($ScratchPreflight) {
            Write-Host "Starting Hermes Finance scratch preflight reader..." -ForegroundColor Cyan
            $backendProcess = Start-Process -FilePath $uv -ArgumentList $backendArguments -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru
        }
        elseif ($previewRequested) {
            Write-Host "Starting Hermes Finance isolated Preview backend..." -ForegroundColor Cyan
            $backendProcess = Start-Process -FilePath $uv -ArgumentList $backendArguments -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru
            $previewProcessIdentity = Get-HermesPreviewProcessIdentity -Backend $backendProcess
        }
        else {
            Write-Host "Starting Hermes Finance production backend..." -ForegroundColor Cyan
            $backendProcess = Start-Process -FilePath $uv -ArgumentList $backendArguments -WorkingDirectory $backendDir -NoNewWindow -PassThru
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

    if ($ScratchPreflight) {
        Wait-ForScratchPreflight -Backend $backendProcess -Token $scratchToken -Binding $scratchBinding
    }
    elseif ($previewRequested) {
        Wait-ForPreviewStack -Backend $backendProcess -Identity $previewProcessIdentity -Binding $previewBinding -Port $selectedPort
    }
    else {
        Wait-ForProductionStack `
        -Backend $backendProcess `
        -RequireRecoverySurfaces ([bool]$RecoveryReadiness) `
        -ExpectedRecoveryToken $env:HERMES_FINANCE_RECOVERY_READINESS_TOKEN `
        -ExpectedDatabaseIdentity $env:HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY `
        -ExpectedCheckoutSha $env:HERMES_FINANCE_RECOVERY_CHECKOUT_SHA
    }
    Write-Host "Hermes Finance is ready: http://127.0.0.1:$selectedPort" -ForegroundColor Green
    if ($ExitAfterReady) {
        if ($ScratchPreflight) {
            Write-Host "Scratch preflight readiness smoke test passed." -ForegroundColor Green
        }
        elseif ($previewRequested) {
            Write-Host "Preview readiness smoke test passed." -ForegroundColor Green
        }
        else {
            Write-Host "Production readiness smoke test passed." -ForegroundColor Green
        }
    }
    else {
        Write-Host "Press Ctrl+C to stop Hermes Finance." -ForegroundColor DarkGray
        while ($true) {
            Assert-ProcessRunning -Process $backendProcess -Name "Backend"
            if ($previewRequested) {
                $current = Get-HermesPreviewProcessIdentity -Backend $backendProcess
                if ($current.CreationTicks -ne $previewProcessIdentity.CreationTicks -or $current.ExecutablePath -ine $previewProcessIdentity.ExecutablePath) { throw "Preview process identity changed." }
            }
            Start-Sleep -Seconds 1
        }
    }
}
catch {
    if ($RecoveryReadiness) {
        $classification = Get-HermesRecoveryReadinessClassification -ErrorRecord $_
        if ([string]::IsNullOrWhiteSpace($classification)) {
            $classification = "readiness_probe_defect"
        }
        Write-Output ("HERMES_RECOVERY_READINESS_FAILURE=" + $classification)
        Write-Host "ERROR: Recovery readiness failed ($classification)." -ForegroundColor Red
    }
    elseif ($ScratchPreflight) {
        Write-Host "ERROR: Scratch preflight failed closed." -ForegroundColor Red
    }
    else {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    }
    $exitCode = 1
}
finally {
    Stop-ProcessTree -Process $backendProcess -Name "backend"
}

exit $exitCode
