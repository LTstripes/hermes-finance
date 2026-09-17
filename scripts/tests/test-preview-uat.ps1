[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$libraryPath = Join-Path $PSScriptRoot "..\prepare-preview-lib.ps1"
. ([IO.Path]::GetFullPath($libraryPath))

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("hermes preview 404 " + [guid]::NewGuid().ToString("N"))
$remotePath = Join-Path $testRoot "remote.git"
$seedPath = Join-Path $testRoot "seed repo"
$controlPath = Join-Path $testRoot "control checkout"
$stablePath = Join-Path $testRoot "stable checkout"
$stableDataPath = Join-Path $testRoot "stable data"
$stableDatabasePath = Join-Path $stableDataPath "stable.sqlite"
$foreignRemotePath = Join-Path $testRoot "foreign.git"
$foreignSeedPath = Join-Path $testRoot "foreign seed"
$powerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$gitPath = (Get-Command git.exe -ErrorAction Stop).Source

function Invoke-TestCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [AllowEmptyCollection()]
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )

    Push-Location $WorkingDirectory
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $FilePath @Arguments 2>&1 | Out-String
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "Synthetic command failed (exit $exitCode): $FilePath $([string]::Join(' ', @($Arguments)))$([Environment]::NewLine)$output"
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $output.Trim()
    }
}

function Invoke-TestGit {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    return Invoke-TestCommand -FilePath $gitPath -WorkingDirectory $WorkingDirectory -Arguments $Arguments -AllowFailure:$AllowFailure
}

function Get-TestGitText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return (Invoke-TestGit -WorkingDirectory $WorkingDirectory -Arguments $Arguments).Output.Trim()
}

function Assert-Test {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw "Synthetic assertion failed: $Message"
    }
}

function Assert-TestEqual {
    param(
        [Parameter(Mandatory = $true)]
        $Expected,
        [Parameter(Mandatory = $true)]
        $Actual,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if ([string]$Expected -cne [string]$Actual) {
        throw "Synthetic assertion failed: $Message (expected '$Expected', got '$Actual')."
    }
}

function Assert-TestFailure {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Operation,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedText,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $failed = $false
    $message = ""
    try {
        & $Operation
    }
    catch {
        $failed = $true
        $message = [string]$_.Exception.Message
    }
    Assert-Test -Condition $failed -Message "$Label must fail closed."
    Assert-Test -Condition ($message.Contains($ExpectedText)) -Message "$Label failure must contain '$ExpectedText'; got '$message'."
    return $message
}

function Write-TestText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Content
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function New-TestDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function New-TestCandidateCommit {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("clean", "prepare-failure", "validate-failure")]
        [string]$MarkerName
    )

    $prepareFlag = Join-Path $seedPath "prepare-failure.flag"
    $validateFlag = Join-Path $seedPath "validate-failure.flag"
    if (Test-Path -LiteralPath $prepareFlag) {
        Remove-Item -LiteralPath $prepareFlag -Force
    }
    if (Test-Path -LiteralPath $validateFlag) {
        Remove-Item -LiteralPath $validateFlag -Force
    }
    if ($MarkerName -eq "prepare-failure") {
        Write-TestText -Path $prepareFlag -Content "synthetic"
    }
    elseif ($MarkerName -eq "validate-failure") {
        Write-TestText -Path $validateFlag -Content "synthetic"
    }
    Write-TestText -Path (Join-Path $seedPath "candidate-marker.txt") -Content ("$MarkerName-" + [guid]::NewGuid().ToString("N"))
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("add", "-A") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("commit", "-m", "synthetic $MarkerName candidate") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("push", "origin", "HEAD:main") | Out-Null
    return Get-TestGitText -WorkingDirectory $seedPath -Arguments @("rev-parse", "HEAD")
}

function Get-PreviewPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PreviewName
    )

    $data = Join-Path $testRoot "$PreviewName data"
    return [pscustomobject]@{
        Checkout = Join-Path $testRoot $PreviewName
        Data     = $data
        Database = Join-Path $data "preview.sqlite"
    }
}

function Invoke-PreviewPreparation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CandidateSha,
        [Parameter(Mandatory = $true)]
        [string]$PreviewName
    )

    $paths = Get-PreviewPath -PreviewName $PreviewName
    $parameters = @{
        CandidateSha       = $CandidateSha
        ControlCheckout    = $controlPath
        PreviewCheckout    = $paths.Checkout
        PreviewDataDirectory = $paths.Data
        PreviewDatabase    = $paths.Database
        StableCheckout     = $stablePath
        StableDataDirectory = $stableDataPath
        StableDatabase     = $stableDatabasePath
        RepositoryUrl      = $remotePath
        CommandRunner      = New-HermesPreviewCommandRunner
        CommandResolver    = New-HermesPreviewCommandResolver
    }
    return Invoke-HermesPreviewPreparation @parameters
}

function New-TestHardlink {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $result = Invoke-TestCommand -FilePath "cmd.exe" -WorkingDirectory $testRoot -Arguments @("/c", "mklink", "/H", $Destination, $Source) -AllowFailure
    Assert-Test -Condition ($result.ExitCode -eq 0) -Message "mklink /H must be available for the synthetic hardlink boundary test."
}

function New-TestJunction {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $result = Invoke-TestCommand -FilePath "cmd.exe" -WorkingDirectory $testRoot -Arguments @("/c", "mklink", "/J", $Destination, $Source) -AllowFailure
    Assert-Test -Condition ($result.ExitCode -eq 0) -Message "mklink /J must be available for the synthetic junction boundary test."
}

function Invoke-PreviewFailure {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CandidateSha,
        [Parameter(Mandatory = $true)]
        [string]$PreviewName,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedText
    )

    $failure = {
        Invoke-PreviewPreparation -CandidateSha $CandidateSha -PreviewName $PreviewName | Out-Null
    }.GetNewClosure()
    return Assert-TestFailure -Label "Preview candidate $PreviewName" -ExpectedText $ExpectedText -Operation $failure
}

function Invoke-DirectPreparation {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Parameters
    )

    return Invoke-HermesPreviewPreparation @Parameters
}

try {
    New-TestDirectory -Path $testRoot
    New-TestDirectory -Path $seedPath
    New-TestDirectory -Path $stableDataPath

    Invoke-TestGit -WorkingDirectory $testRoot -Arguments @("init", "--bare", $remotePath) | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("init", "--initial-branch", "main") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("config", "user.email", "preview-uat@example.com") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("config", "user.name", "Preview UAT Synthetic") | Out-Null
    Write-TestText -Path (Join-Path $seedPath ".gitignore") -Content @'
.env
.env.*
backend/.venv/
frontend/node_modules/
frontend/dist/
data/*
!data/.gitkeep
.hermes-runtime-prepared.json
.hermes-data-identity.json
target-runtime.log
target-start.log
'@
    Write-TestText -Path (Join-Path $seedPath "README.md") -Content "synthetic Preview/UAT fixture"
    Write-TestText -Path (Join-Path $seedPath "data/.gitkeep") -Content ""
    Write-TestText -Path (Join-Path $seedPath "scripts/prepare-runtime.ps1") -Content @'
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Checkout,
    [switch]$Prepare,
    [switch]$Validate
)
$ErrorActionPreference = "Stop"
$log = Join-Path $Checkout "target-runtime.log"
$mode = if ($Prepare) { "Prepare" } else { "Validate" }
Add-Content -LiteralPath $log -Value ("mode=$mode;cwd=$((Get-Location).Path);checkout=$Checkout")
if ($Prepare) {
    if (Test-Path -LiteralPath (Join-Path $Checkout "prepare-failure.flag")) {
        exit 31
    }
    Set-Content -LiteralPath (Join-Path $Checkout ".hermes-runtime-prepared.json") -Value '{"prepared":true}' -Encoding UTF8
}
if ($Validate) {
    if (Test-Path -LiteralPath (Join-Path $Checkout "validate-failure.flag")) {
        exit 32
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Checkout ".hermes-runtime-prepared.json"))) {
        exit 33
    }
}
'@
    Write-TestText -Path (Join-Path $seedPath "candidate-marker.txt") -Content "clean"
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("add", "-A") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("commit", "-m", "synthetic clean candidate") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("remote", "add", "origin", $remotePath) | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("push", "origin", "HEAD:main") | Out-Null
    Invoke-TestGit -WorkingDirectory $remotePath -Arguments @("symbolic-ref", "HEAD", "refs/heads/main") | Out-Null
    $candidateOne = Get-TestGitText -WorkingDirectory $seedPath -Arguments @("rev-parse", "HEAD")

    Invoke-TestGit -WorkingDirectory $testRoot -Arguments @("clone", $remotePath, $controlPath) | Out-Null
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("config", "user.email", "preview-uat@example.com") | Out-Null
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("config", "user.name", "Preview UAT Synthetic") | Out-Null
    Invoke-TestGit -WorkingDirectory $testRoot -Arguments @("clone", $remotePath, $stablePath) | Out-Null
    Write-TestText -Path $stableDatabasePath -Content "stable synthetic database"

    $context = [pscustomobject]@{
        GitPath        = $gitPath
        PowerShellPath = $powerShellPath
        CommandRunner  = New-HermesPreviewCommandRunner
    }
    $controlBefore = Get-HermesPreviewGitSnapshot -Context $context -Checkout $controlPath -Label "Control checkout"
    $stableBefore = Get-HermesPreviewGitSnapshot -Context $context -Checkout $stablePath -Label "Stable checkout"
    $stableDatabaseBefore = Get-Content -LiteralPath $stableDatabasePath -Raw

    Write-TestText -Path (Join-Path $controlPath ".env") -Content "synthetic-secret-must-not-copy"
    Write-TestText -Path (Join-Path $controlPath "backend/.venv/ignored.txt") -Content "ignored"
    Write-TestText -Path (Join-Path $controlPath "frontend/node_modules/ignored.txt") -Content "ignored"
    Write-TestText -Path (Join-Path $controlPath "frontend/dist/ignored.txt") -Content "ignored"
    $first = Invoke-PreviewPreparation -CandidateSha $candidateOne -PreviewName "preview exact path"
    $firstPaths = Get-PreviewPath -PreviewName "preview exact path"
    Assert-TestEqual -Expected "prepared" -Actual $first.Status -Message "exact full SHA succeeds"
    Assert-TestEqual -Expected $candidateOne -Actual (Get-TestGitText -WorkingDirectory $firstPaths.Checkout -Arguments @("rev-parse", "HEAD")) -Message "Preview is pinned to the exact SHA"
    Assert-TestEqual -Expected $candidateOne -Actual $first.CandidateSha -Message "result reports the exact SHA"
    Assert-Test -Condition (Test-Path -LiteralPath (Join-Path $firstPaths.Checkout ".git") -PathType Container) -Message "Preview has its own .git directory"
    Assert-Test -Condition ($first.SidecarKind -ceq "preview") -Message "result reports sidecar kind preview"
    $sidecar = Get-Content -LiteralPath (Join-Path $firstPaths.Data ".hermes-data-identity.json") -Raw | ConvertFrom-Json
    Assert-Test -Condition ($sidecar.kind -ceq "preview") -Message "sidecar declares kind=preview"
    Assert-Test -Condition (-not (Test-Path -LiteralPath (Join-Path $firstPaths.Checkout "target-start.log"))) -Message "operation does not auto-start"
    Assert-Test -Condition (-not (Test-Path -LiteralPath (Join-Path $firstPaths.Checkout ".env"))) -Message "ignored .env is not copied"
    Assert-Test -Condition (-not (Test-Path -LiteralPath (Join-Path $firstPaths.Checkout "backend/.venv/ignored.txt"))) -Message "ignored backend runtime is not copied"
    Assert-Test -Condition (-not (Test-Path -LiteralPath (Join-Path $firstPaths.Checkout "frontend/node_modules/ignored.txt"))) -Message "ignored frontend runtime is not copied"
    $runtimeLog = Get-Content -LiteralPath (Join-Path $firstPaths.Checkout "target-runtime.log") -Raw
    Assert-Test -Condition ($runtimeLog.Contains("cwd=$($firstPaths.Checkout)") -and $runtimeLog.Contains("checkout=$($firstPaths.Checkout)")) -Message "Prepare/Validate run with target checkout cwd"
    Assert-Test -Condition (Test-HermesPreviewSamePath -Left (Get-HermesPreviewGitCommonDirectory -Context $context -Checkout $firstPaths.Checkout) -Right (Get-HermesPreviewGitDirectory -Context $context -Checkout $firstPaths.Checkout)) -Message "Preview Git common directory is its own Git directory"

    $entrypointPaths = Get-PreviewPath -PreviewName "preview public entrypoint"
    $entrypointPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\prepare-preview.ps1"))
    $entrypointArguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $entrypointPath,
        "-CandidateSha", $candidateOne,
        "-ControlCheckout", $controlPath,
        "-PreviewCheckout", $entrypointPaths.Checkout,
        "-PreviewDataDirectory", $entrypointPaths.Data,
        "-PreviewDatabase", $entrypointPaths.Database,
        "-StableCheckout", $stablePath,
        "-StableDataDirectory", $stableDataPath,
        "-StableDatabase", $stableDatabasePath,
        "-RepositoryUrl", $remotePath
    )
    $entrypointResult = Invoke-TestCommand -FilePath $powerShellPath -WorkingDirectory $testRoot -Arguments $entrypointArguments
    Assert-Test -Condition ($entrypointResult.Output.Contains("candidate_sha=$candidateOne")) -Message "public owner entrypoint reports the exact candidate"
    Assert-TestEqual -Expected $candidateOne -Actual (Get-TestGitText -WorkingDirectory $entrypointPaths.Checkout -Arguments @("rev-parse", "HEAD")) -Message "public owner entrypoint pins exact SHA"

    # Tracked dot-prefixed private/runtime paths must remain visible to the candidate-tree guard.
    Write-TestText -Path (Join-Path $seedPath ".env") -Content "synthetic-private-fixture"
    Write-TestText -Path (Join-Path $seedPath ".hermes-runtime-prepared.json") -Content '{"synthetic":true}'
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("add", "-f", ".env", ".hermes-runtime-prepared.json") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("commit", "-m", "synthetic tracked private runtime candidate") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("push", "origin", "HEAD:main") | Out-Null
    $trackedPrivateSha = Get-TestGitText -WorkingDirectory $seedPath -Arguments @("rev-parse", "HEAD")
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("fetch", "--no-tags", "origin", "main") | Out-Null
    $failure = {
        Invoke-PreviewPreparation -CandidateSha $trackedPrivateSha -PreviewName "preview tracked private runtime" | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "tracked dot-prefixed private/runtime paths" -ExpectedText "tracked private or runtime path" -Operation $failure | Out-Null
    Remove-Item -LiteralPath (Join-Path $seedPath ".env") -Force
    Remove-Item -LiteralPath (Join-Path $seedPath ".hermes-runtime-prepared.json") -Force
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("add", "-A") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("commit", "-m", "synthetic clean candidate after private path guard") | Out-Null
    Invoke-TestGit -WorkingDirectory $seedPath -Arguments @("push", "origin", "HEAD:main") | Out-Null
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("fetch", "--no-tags", "origin", "main") | Out-Null

    $candidateTwo = New-TestCandidateCommit -MarkerName "clean"
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("fetch", "--no-tags", "origin", "main") | Out-Null
    Assert-Test -Condition ($candidateTwo -ne $candidateOne) -Message "synthetic main advance creates a different full SHA"
    Assert-TestEqual -Expected $candidateOne -Actual (Get-TestGitText -WorkingDirectory $firstPaths.Checkout -Arguments @("rev-parse", "HEAD")) -Message "main advance does not move existing Preview"
    Invoke-PreviewPreparation -CandidateSha $candidateTwo -PreviewName "preview exact path" | Out-Null
    Assert-TestEqual -Expected $candidateTwo -Actual (Get-TestGitText -WorkingDirectory $firstPaths.Checkout -Arguments @("rev-parse", "HEAD")) -Message "explicit repin selects the requested SHA"
    Assert-TestEqual -Expected "preview" -Actual ((Get-Content -LiteralPath (Join-Path $firstPaths.Data ".hermes-data-identity.json") -Raw | ConvertFrom-Json).kind) -Message "repin preserves preview sidecar"

    $failure = {
        Invoke-PreviewPreparation -CandidateSha "main" -PreviewName "preview invalid branch" | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "branch selector" -ExpectedText "full 40-hex" -Operation $failure | Out-Null
    $failure = {
        Invoke-PreviewPreparation -CandidateSha $candidateOne.Substring(0, 8) -PreviewName "preview ambiguous prefix" | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "abbreviated ambiguous selector" -ExpectedText "full 40-hex" -Operation $failure | Out-Null
    $failure = {
        Invoke-PreviewPreparation -CandidateSha ("0" * 40) -PreviewName "preview nonexistent sha" | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "nonexistent full SHA" -ExpectedText "could not get object info" -Operation $failure | Out-Null

    New-TestDirectory -Path $foreignSeedPath
    Invoke-TestGit -WorkingDirectory $testRoot -Arguments @("init", "--bare", $foreignRemotePath) | Out-Null
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("init", "--initial-branch", "main") | Out-Null
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("config", "user.email", "foreign@example.com") | Out-Null
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("config", "user.name", "Foreign Synthetic") | Out-Null
    Write-TestText -Path (Join-Path $foreignSeedPath "foreign.txt") -Content "foreign"
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("add", "-A") | Out-Null
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("commit", "-m", "foreign candidate") | Out-Null
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("remote", "add", "origin", $foreignRemotePath) | Out-Null
    Invoke-TestGit -WorkingDirectory $foreignSeedPath -Arguments @("push", "origin", "HEAD:main") | Out-Null
    $foreignSha = Get-TestGitText -WorkingDirectory $foreignSeedPath -Arguments @("rev-parse", "HEAD")
    $failure = {
        Invoke-PreviewPreparation -CandidateSha $foreignSha -PreviewName "preview foreign sha" | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "foreign SHA" -ExpectedText "could not get object info" -Operation $failure | Out-Null
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("remote", "set-url", "origin", $foreignRemotePath) | Out-Null
    $failure = {
        Invoke-PreviewPreparation -CandidateSha $candidateOne -PreviewName "preview wrong repository" | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "wrong repository" -ExpectedText "expected Hermes Finance repository" -Operation $failure | Out-Null
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("remote", "set-url", "origin", $remotePath) | Out-Null

    Assert-TestEqual -Expected $stableBefore.Head -Actual (Get-TestGitText -WorkingDirectory $stablePath -Arguments @("rev-parse", "HEAD")) -Message "Stable HEAD is unchanged"
    Assert-TestEqual -Expected $stableBefore.Status -Actual (Get-TestGitText -WorkingDirectory $stablePath -Arguments @("status", "--porcelain=v1", "--untracked-files=all")) -Message "Stable status is unchanged"
    Assert-TestEqual -Expected $stableDatabaseBefore -Actual (Get-Content -LiteralPath $stableDatabasePath -Raw) -Message "Stable database is unchanged"

    $linkedPreview = Join-Path $testRoot "linked preview"
    $linkedData = Join-Path $testRoot "linked preview data"
    New-TestDirectory -Path $linkedData
    Write-TestText -Path (Join-Path $linkedData ".hermes-data-identity.json") -Content '{"kind":"preview"}'
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("worktree", "add", "--detach", $linkedPreview, $candidateOne) | Out-Null
    $parameters = @{
        CandidateSha = $candidateOne
        ControlCheckout = $controlPath
        PreviewCheckout = $linkedPreview
        PreviewDataDirectory = $linkedData
        PreviewDatabase = Join-Path $linkedData "preview.sqlite"
        StableCheckout = $stablePath
        StableDataDirectory = $stableDataPath
        StableDatabase = $stableDatabasePath
        RepositoryUrl = $remotePath
        CommandRunner = New-HermesPreviewCommandRunner
        CommandResolver = New-HermesPreviewCommandResolver
    }
    $failure = {
        Invoke-DirectPreparation -Parameters $parameters | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "linked worktree" -ExpectedText "independent Git clone" -Operation $failure | Out-Null
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("worktree", "remove", "--force", $linkedPreview) | Out-Null

    $aliasPaths = Get-PreviewPath -PreviewName "preview direct alias"
    New-TestDirectory -Path $aliasPaths.Data
    Write-TestText -Path (Join-Path $aliasPaths.Data ".hermes-data-identity.json") -Content '{"kind":"preview"}'
    $parameters.PreviewCheckout = $aliasPaths.Checkout
    $parameters.PreviewDataDirectory = $aliasPaths.Data
    $parameters.PreviewDatabase = $stableDatabasePath
    $failure = {
        Invoke-DirectPreparation -Parameters $parameters | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "direct database alias" -ExpectedText "inside the Preview data directory" -Operation $failure | Out-Null

    $hardlinkPaths = Get-PreviewPath -PreviewName "preview hardlink"
    New-TestDirectory -Path $hardlinkPaths.Data
    Write-TestText -Path (Join-Path $hardlinkPaths.Data ".hermes-data-identity.json") -Content '{"kind":"preview"}'
    New-TestHardlink -Source $stableDatabasePath -Destination $hardlinkPaths.Database
    $parameters.PreviewCheckout = $hardlinkPaths.Checkout
    $parameters.PreviewDataDirectory = $hardlinkPaths.Data
    $parameters.PreviewDatabase = $hardlinkPaths.Database
    $failure = {
        Invoke-DirectPreparation -Parameters $parameters | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "hardlink database alias" -ExpectedText "file identity" -Operation $failure | Out-Null

    $junctionPaths = Get-PreviewPath -PreviewName "preview junction"
    New-TestJunction -Source $stableDataPath -Destination $junctionPaths.Data
    $parameters.PreviewCheckout = $junctionPaths.Checkout
    $parameters.PreviewDataDirectory = $junctionPaths.Data
    $parameters.PreviewDatabase = $junctionPaths.Database
    $failure = {
        Invoke-DirectPreparation -Parameters $parameters | Out-Null
    }.GetNewClosure()
    Assert-TestFailure -Label "junction data alias" -ExpectedText "reparse" -Operation $failure | Out-Null

    $candidateThree = New-TestCandidateCommit -MarkerName "prepare-failure"
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("fetch", "--no-tags", "origin", "main") | Out-Null
    $failureMessage = Invoke-PreviewFailure -CandidateSha $candidateThree -PreviewName "preview prepare failure" -ExpectedText "target-pinned-but-unprepared"
    Assert-Test -Condition ($failureMessage.Contains("fallback=not-attempted") -and $failureMessage.Contains("auto-start=not-attempted")) -Message "Prepare failure reports no fallback and no auto-start"
    $failurePaths = Get-PreviewPath -PreviewName "preview prepare failure"
    Assert-TestEqual -Expected $candidateThree -Actual (Get-TestGitText -WorkingDirectory $failurePaths.Checkout -Arguments @("rev-parse", "HEAD")) -Message "Prepare failure leaves exact candidate pinned"
    Assert-Test -Condition (-not (Test-Path -LiteralPath (Join-Path $failurePaths.Checkout "target-start.log"))) -Message "Prepare failure does not start"

    $candidateFour = New-TestCandidateCommit -MarkerName "validate-failure"
    Invoke-TestGit -WorkingDirectory $controlPath -Arguments @("fetch", "--no-tags", "origin", "main") | Out-Null
    $failureMessage = Invoke-PreviewFailure -CandidateSha $candidateFour -PreviewName "preview validate failure" -ExpectedText "target-pinned-but-unvalidated"
    Assert-Test -Condition ($failureMessage.Contains("fallback=not-attempted") -and $failureMessage.Contains("auto-start=not-attempted")) -Message "Validate failure reports no fallback and no auto-start"
    $failurePaths = Get-PreviewPath -PreviewName "preview validate failure"
    Assert-TestEqual -Expected $candidateFour -Actual (Get-TestGitText -WorkingDirectory $failurePaths.Checkout -Arguments @("rev-parse", "HEAD")) -Message "Validate failure leaves exact candidate pinned"
    Assert-Test -Condition (-not (Test-Path -LiteralPath (Join-Path $failurePaths.Checkout "target-start.log"))) -Message "Validate failure does not start"

    Assert-TestEqual -Expected $stableBefore.Head -Actual (Get-TestGitText -WorkingDirectory $stablePath -Arguments @("rev-parse", "HEAD")) -Message "Stable remains unchanged after all failure cases"
    Assert-TestEqual -Expected $stableDatabaseBefore -Actual (Get-Content -LiteralPath $stableDatabasePath -Raw) -Message "Stable data remains unchanged after all failure cases"
    Assert-HermesPreviewGitSnapshotUnchanged -Context $context -Snapshot $controlBefore -Label "Control checkout"

    Write-Output "Preview/UAT exact-pin synthetic safety regression: PASS"
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
