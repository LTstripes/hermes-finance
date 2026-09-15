# Deterministic synthetic regressions for the explicit Stable update operation.
# The GitHub/remote layer is faked; the accepted SQLite backup helper and a
# synthetic target Prepare/Validate script are exercised in temporary paths.

[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$scriptRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $scriptRoot "release-lib.ps1")
. (Join-Path $scriptRoot "release-request-lib.ps1")
. (Join-Path $scriptRoot "update-stable-lib.ps1")

$script:Passed = 0
$script:Failed = 0
$script:TempRoots = New-Object System.Collections.ArrayList
$script:CurrentSha = "1111111111111111111111111111111111111111"
$script:TargetSha = "2222222222222222222222222222222222222222"
$script:CanonicalUrl = "https://github.com/LTstripes/hermes-finance.git"
$pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
$script:UvExecutable = (Get-Command "uv.exe" -ErrorAction SilentlyContinue).Source
if ($null -ne $pythonCommand) {
    $script:PythonExecutable = $pythonCommand.Source
    $script:PythonUsesUv = $false
}
elseif (-not [string]::IsNullOrWhiteSpace($script:UvExecutable)) {
    # The managed developer image exposes Python through uv, while the CI
    # Windows runner normally has python.exe directly on PATH. Prefer the
    # interpreter path so helper JSON is not contaminated by uv diagnostics.
    $uvPython = & $script:UvExecutable python find 2>$null | Select-Object -First 1
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$uvPython)) {
        $script:PythonExecutable = [string]$uvPython
        $script:PythonUsesUv = $false
    }
    else {
        $script:PythonExecutable = $script:UvExecutable
        $script:PythonUsesUv = $true
    }
}
else {
    throw "Synthetic Stable update regressions require python.exe or uv.exe."
}
$script:PowerShellExecutable = (Get-Command "powershell.exe" -ErrorAction Stop).Source

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

function Assert-Equal {
    param(
        $Expected,
        $Actual,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ($Expected -ne $Actual) {
        throw "Expected $Label to be [$Expected], got [$Actual]."
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    [IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function New-TestTagObjectSha {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommitSha
    )

    return "a$($CommitSha.Substring(1))"
}

function New-TestResult {
    param(
        [int]$ExitCode = 0,
        [string]$Stdout = "",
        [string]$Stderr = ""
    )

    return [pscustomobject]@{
        ExitCode = $ExitCode
        Stdout   = $Stdout
        Stderr   = $Stderr
    }
}

function Invoke-TestPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    if ($script:PythonUsesUv) {
        & $script:PythonExecutable run python @Arguments
    }
    else {
        & $script:PythonExecutable @Arguments
    }
    return $LASTEXITCODE
}

function Get-TestFlagValue {
    param(
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Flag
    )

    $items = @($Arguments)
    for ($i = 0; $i -lt $items.Count - 1; $i++) {
        if ([string]$items[$i] -eq $Flag) {
            return [string]$items[$i + 1]
        }
    }

    return $null
}

function New-TestTargetPrepareScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Write-Utf8NoBom -Path $Path -Content @'
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Checkout,
    [switch]$Prepare,
    [switch]$Validate
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$log = Join-Path $Checkout "target-prepare-calls.log"
$marker = Join-Path $Checkout ".synthetic-target-prepared"
if ($Prepare) {
    Add-Content -LiteralPath $log -Value "Prepare"
    New-Item -ItemType File -Force -Path $marker | Out-Null
}
if ($Validate) {
    Add-Content -LiteralPath $log -Value "Validate"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        exit 8
    }
}
Write-Output "runtime=prepared"
'@
}

function New-TestWorld {
    param(
        [string]$CurrentVersion = "0.8.2",
        [string]$TargetVersion = "0.8.3",
        [string]$TargetPackageVersion = $TargetVersion,
        [string]$TargetProjectVersion = $TargetVersion,
        [string[]]$CurrentTags = $null,
        [string]$Status = "",
        [switch]$WrongOrigin,
        [switch]$Occupied,
        [switch]$TargetMissing,
        [switch]$TargetUnannotated,
        [switch]$TargetDraft,
        [switch]$TargetPrerelease,
        [switch]$TargetReleaseTagMismatch,
        [switch]$BackupFailure,
        [switch]$FetchFailure,
        [switch]$SwitchFailure,
        [switch]$SwitchIgnoredCollision,
        [switch]$PrepareFailure,
        [switch]$ValidateFailure,
        [string[]]$TargetTreePaths = $null,
        [string[]]$CurrentTrackedPaths = $null,
        [string[]]$IgnoredPaths = $null,
        [switch]$LocalTargetAlreadyPresent
    )

    if ($null -eq $CurrentTags) {
        $CurrentTags = @("v$CurrentVersion")
    }
    if ($null -eq $TargetTreePaths) {
        $TargetTreePaths = @(
            "data/.gitkeep",
            "backend/pyproject.toml",
            "backend/src/hermes_finance/__init__.py",
            "docs/release-notes-$TargetVersion.md",
            "scripts/prepare-runtime.ps1"
        )
    }
    if ($null -eq $IgnoredPaths) {
        $IgnoredPaths = @("data/finance.db")
    }
    if ($null -eq $CurrentTrackedPaths) {
        $CurrentTrackedPaths = @(
            "data/.gitkeep",
            "backend/pyproject.toml",
            "backend/src/hermes_finance/__init__.py",
            "docs/release-notes-$CurrentVersion.md",
            "scripts/prepare-runtime.ps1"
        )
    }

    $root = Join-Path ([IO.Path]::GetTempPath()) ("hermes r09 ops02 " + [guid]::NewGuid().ToString("N"))
    $control = Join-Path $root "trusted control checkout"
    $stable = Join-Path $root "Stable Checkout With Spaces"
    $data = Join-Path $stable "data"
    $database = Join-Path $data "finance.db"
    $backup = Join-Path $data "backups"
    $targetTag = "v$TargetVersion"
    $currentTag = "v$CurrentVersion"
    $origin = $script:CanonicalUrl
    if ($WrongOrigin) {
        $origin = "https://github.com/example/not-hermes.git"
    }

    New-Item -ItemType Directory -Force -Path @(
        (Join-Path $control "scripts"),
        (Join-Path $stable "scripts"),
        $data,
        (Join-Path $stable "backend/src/hermes_finance"),
        (Join-Path $stable "docs")
    ) | Out-Null
    Copy-Item -LiteralPath (Join-Path $scriptRoot "launcher-production-backup.py") -Destination (Join-Path $control "scripts/launcher-production-backup.py")
    New-TestTargetPrepareScript -Path (Join-Path $stable "scripts/prepare-runtime.ps1")
    Write-Utf8NoBom `
        -Path (Join-Path $stable "backend/pyproject.toml") `
        -Content ('[project]' + [Environment]::NewLine + 'version = "' + $TargetProjectVersion + '"' + [Environment]::NewLine)
    Write-Utf8NoBom `
        -Path (Join-Path $stable "backend/src/hermes_finance/__init__.py") `
        -Content ('__version__ = "' + $TargetPackageVersion + '"' + [Environment]::NewLine)
    Write-Utf8NoBom -Path (Join-Path $stable "docs/release-notes-$TargetVersion.md") -Content "Synthetic release notes.`n"
    New-Item -ItemType File -Force -Path (Join-Path $stable "data/.gitkeep") | Out-Null
    [void]$script:TempRoots.Add($root)

    $pythonCode = "import sqlite3,sys; sqlite3.connect(sys.argv[1]).close()"
    $pythonExitCode = Invoke-TestPython -Arguments @("-c", $pythonCode, $database)
    if ($pythonExitCode -ne 0) {
        throw "Could not create the synthetic SQLite database."
    }

    $state = @{
        Root                    = $root
        Control                 = $control
        Stable                  = $stable
        Database                = $database
        Backup                  = $backup
        Origin                  = $origin
        CurrentVersion          = $CurrentVersion
        TargetVersion           = $TargetVersion
        CurrentTag              = $currentTag
        TargetTag               = $targetTag
        CurrentSha              = $script:CurrentSha
        TargetSha               = $script:TargetSha
        CurrentTags             = @($CurrentTags)
        Status                  = $Status
        TargetPackageVersion    = $TargetPackageVersion
        TargetProjectVersion    = $TargetProjectVersion
        TargetTreePaths         = @($TargetTreePaths)
        CurrentTrackedPaths     = @($CurrentTrackedPaths)
        IgnoredPaths            = @($IgnoredPaths)
        TargetMissing           = [bool]$TargetMissing
        TargetUnannotated       = [bool]$TargetUnannotated
        TargetDraft             = [bool]$TargetDraft
        TargetPrerelease        = [bool]$TargetPrerelease
        TargetReleaseTagMismatch = [bool]$TargetReleaseTagMismatch
        BackupFailure           = [bool]$BackupFailure
        FetchFailure            = [bool]$FetchFailure
        SwitchFailure           = [bool]$SwitchFailure
        SwitchIgnoredCollision  = [bool]$SwitchIgnoredCollision
        PrepareFailure          = [bool]$PrepareFailure
        ValidateFailure         = [bool]$ValidateFailure
        Occupied                = [bool]$Occupied
        LocalTargetPresent      = [bool]$LocalTargetAlreadyPresent
        Fetched                 = $false
        Switched                = $false
        StableHead              = $script:CurrentSha
        PrepareCalls            = 0
        ValidateCalls           = 0
        IdentityCalls           = 0
        Calls                   = New-Object System.Collections.ArrayList
    }
    $pythonExecutable = [string]$script:PythonExecutable
    $pythonUsesUv = [bool]$script:PythonUsesUv
    $powerShellExecutable = [string]$script:PowerShellExecutable

    $runner = {
        param($Request)

        $arguments = @($Request.Arguments)
        [void]$state.Calls.Add([pscustomobject]@{
                Name      = [string]$Request.Name
                Arguments = $arguments
            })

        switch ([string]$Request.Name) {
            "git" { return Invoke-TestGit -State $state -Arguments $arguments }
            "gh" { return Invoke-TestGh -State $state -Arguments $arguments }
            "python" {
                if ($state.BackupFailure) {
                    return New-TestResult -ExitCode 23 -Stderr "synthetic backup failure"
                }
                $saved = $ErrorActionPreference
                try {
                    $ErrorActionPreference = "Continue"
                    if ($pythonUsesUv) {
                        $output = & $Request.FileName run python @arguments 2>&1 | Out-String
                    }
                    else {
                        $output = & $Request.FileName @arguments 2>&1 | Out-String
                    }
                    $code = $LASTEXITCODE
                }
                finally {
                    $ErrorActionPreference = $saved
                }
                return New-TestResult -ExitCode $code -Stdout $output
            }
            "powershell.exe" {
                $mode = if ($arguments -contains "-Prepare") { "Prepare" } else { "Validate" }
                if ($mode -eq "Prepare") {
                    $state.PrepareCalls++
                    if ($state.PrepareFailure) {
                        return New-TestResult -ExitCode 27 -Stderr "synthetic Prepare failure"
                    }
                }
                else {
                    $state.ValidateCalls++
                    if ($state.ValidateFailure) {
                        return New-TestResult -ExitCode 28 -Stderr "synthetic Validate failure"
                    }
                }
                $saved = $ErrorActionPreference
                try {
                    $ErrorActionPreference = "Continue"
                    $output = & $Request.FileName @arguments 2>&1 | Out-String
                    $code = $LASTEXITCODE
                }
                finally {
                    $ErrorActionPreference = $saved
                }
                return New-TestResult -ExitCode $code -Stdout $output
            }
            default { throw "Unexpected synthetic tool '$($Request.Name)'." }
        }
    }.GetNewClosure()

    $resolver = {
        param([string]$Name)
        switch ($Name) {
            "git" { return "git.exe" }
            "gh" { return "gh.exe" }
            "python.exe" { return $pythonExecutable }
            "powershell.exe" { return $powerShellExecutable }
            default { return $null }
        }
    }.GetNewClosure()

    $portProbe = {
        param([string]$Checkout)
        return (-not [bool]$state.Occupied)
    }.GetNewClosure()

    $identityValidator = {
        param([string]$Checkout, [string]$Version)
        $state.IdentityCalls++
        if ($Version -ne $state.TargetVersion) {
            throw "synthetic identity mismatch"
        }
    }.GetNewClosure()

    return [pscustomobject]@{
        State              = $state
        Runner             = $runner
        Resolver           = $resolver
        PortProbe          = $portProbe
        IdentityValidator  = $identityValidator
    }
}

function Invoke-TestGit {
    param(
        [Parameter(Mandatory = $true)]
        $State,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $gitArgs = @(Get-HermesGitArgsWithoutC -Arguments $Arguments)
    if ($gitArgs.Count -eq 0) {
        throw "Synthetic Git received no arguments."
    }
    $verb = [string]$gitArgs[0]

    if ($verb -eq "rev-parse" -and $gitArgs -contains "--show-toplevel") {
        return New-TestResult -Stdout $State.Stable
    }
    if ($verb -eq "rev-parse" -and $gitArgs -contains "HEAD") {
        return New-TestResult -Stdout $State.StableHead
    }
    if ($verb -eq "rev-parse" -and @($gitArgs | Where-Object { [string]$_ -like "refs/tags/*^{commit}" }).Count -gt 0) {
        $reference = [string]($gitArgs | Where-Object { [string]$_ -like "refs/tags/*^{commit}" } | Select-Object -First 1)
        if ($reference -eq "refs/tags/$($State.CurrentTag)^{commit}") {
            return New-TestResult -Stdout $State.CurrentSha
        }
        if ($reference -eq "refs/tags/$($State.TargetTag)^{commit}" -and $State.LocalTargetPresent) {
            return New-TestResult -Stdout $State.TargetSha
        }
        return New-TestResult -ExitCode 1
    }
    if ($verb -eq "status") {
        return New-TestResult -Stdout $State.Status
    }
    if ($verb -eq "remote" -and $gitArgs -contains "get-url") {
        return New-TestResult -Stdout $State.Origin
    }
    if ($verb -eq "config" -and $gitArgs -contains "remote.origin.mirror") {
        return New-TestResult -ExitCode 1
    }
    if ($verb -eq "for-each-ref") {
        return New-TestResult -Stdout ([string]::Join("`n", $State.CurrentTags))
    }
    if ($verb -eq "show-ref") {
        $reference = [string]$gitArgs[$gitArgs.Count - 1]
        if ($reference -eq "refs/tags/$($State.CurrentTag)") {
            return New-TestResult
        }
        if ($reference -eq "refs/tags/$($State.TargetTag)" -and $State.LocalTargetPresent) {
            return New-TestResult
        }
        return New-TestResult -ExitCode 1
    }
    if ($verb -eq "cat-file" -and $gitArgs -contains "-t") {
        return New-TestResult -Stdout "tag"
    }
    if ($verb -eq "cat-file" -and $gitArgs -contains "-s") {
        return New-TestResult -Stdout "0"
    }
    if ($verb -eq "cat-file" -and $gitArgs -contains "-e") {
        return New-TestResult
    }
    if ($verb -eq "ls-remote") {
        $wanted = [string]$gitArgs[$gitArgs.Count - 1]
        $tag = $null
        if ($wanted -like "refs/tags/*") {
            $tag = $wanted.Substring("refs/tags/".Length).Replace("^{}", "")
        }
        $isCurrent = $tag -eq $State.CurrentTag
        $isTarget = $tag -eq $State.TargetTag
        if (-not $isCurrent -and -not $isTarget) {
            return New-TestResult
        }
        $commit = if ($isCurrent) { $State.CurrentSha } else { $State.TargetSha }
        $tagRef = "refs/tags/$tag"
        if ($wanted -eq ($tagRef + "^{}")) {
            return New-TestResult -Stdout ($commit + "`t" + $tagRef + "^{}")
        }
        if ($wanted -eq $tagRef) {
            $objectSha = New-TestTagObjectSha -CommitSha $commit
            if ($isTarget -and $State.TargetUnannotated) {
                $objectSha = $commit
            }
            return New-TestResult -Stdout "$objectSha`t$tagRef"
        }
        return New-TestResult
    }
    if ($verb -eq "fetch") {
        if ($State.FetchFailure) {
            return New-TestResult -ExitCode 29 -Stderr "synthetic fetch failure"
        }
        $State.Fetched = $true
        $State.LocalTargetPresent = $true
        return New-TestResult
    }
    if ($verb -eq "show") {
        $object = [string]$gitArgs[$gitArgs.Count - 1]
        if ($object -like "*:backend/src/hermes_finance/__init__.py") {
            return New-TestResult -Stdout ('__version__ = "' + $State.TargetPackageVersion + '"' + [Environment]::NewLine)
        }
        if ($object -like "*:backend/pyproject.toml") {
            return New-TestResult -Stdout ('[project]' + [Environment]::NewLine + 'version = "' + $State.TargetProjectVersion + '"' + [Environment]::NewLine)
        }
        throw "Unexpected synthetic Git blob request: $object"
    }
    if ($verb -eq "ls-tree") {
        return New-TestResult -Stdout (([string]::Join([char]0, $State.TargetTreePaths)) + [char]0)
    }
    if ($verb -eq "ls-files") {
        if ($gitArgs -contains "--others") {
            return New-TestResult -Stdout (([string]::Join([char]0, $State.IgnoredPaths)) + [char]0)
        }
        return New-TestResult -Stdout (([string]::Join([char]0, $State.CurrentTrackedPaths)) + [char]0)
    }
    if ($verb -eq "switch") {
        if ($State.SwitchFailure -or $State.SwitchIgnoredCollision) {
            return New-TestResult -ExitCode 31 -Stderr "synthetic checkout switch failure"
        }
        $State.Switched = $true
        $State.StableHead = $State.TargetSha
        return New-TestResult
    }

    throw "Unexpected synthetic Git command: $([string]::Join(' ', $gitArgs))"
}

function Invoke-TestGh {
    param(
        [Parameter(Mandatory = $true)]
        $State,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    if ($Arguments.Count -lt 2 -or $Arguments[0] -ne "api") {
        throw "Stable update must only use the read-only GitHub Release API."
    }
    $apiPath = [string]($Arguments | Where-Object { [string]$_ -like "repos/LTstripes/hermes-finance/releases/tags/*" } | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($apiPath)) {
        throw "Unexpected synthetic GitHub API path."
    }
    $tag = $apiPath.Substring($apiPath.LastIndexOf("/") + 1)
    $isCurrent = $tag -eq $State.CurrentTag
    $isTarget = $tag -eq $State.TargetTag
    if (-not $isCurrent -and -not $isTarget) {
        return New-TestResult -ExitCode 1 -Stderr "Not Found (HTTP 404)"
    }
    if ($isTarget -and $State.TargetMissing) {
        return New-TestResult -ExitCode 1 -Stderr "Not Found (HTTP 404)"
    }

    $releaseTag = $tag
    if ($isTarget -and $State.TargetReleaseTagMismatch) {
        $releaseTag = "v9.9.9"
    }
    $payload = @{
        tag_name   = $releaseTag
        draft      = if ($isTarget) { $State.TargetDraft } else { $false }
        prerelease = if ($isTarget) { $State.TargetPrerelease } else { $false }
        html_url   = "https://github.com/LTstripes/hermes-finance/releases/tag/$releaseTag"
    }
    return New-TestResult -Stdout ($payload | ConvertTo-Json -Compress)
}

function Invoke-TestUpdate {
    param(
        [Parameter(Mandatory = $true)]
        $World,
        [string]$TargetVersion = $World.State.TargetVersion,
        [string]$ControlCheckout = $World.State.Control
    )

    return Invoke-HermesStableUpdate `
        -StableCheckout $World.State.Stable `
        -TargetVersion $TargetVersion `
        -DatabasePath $World.State.Database `
        -BackupDirectory $World.State.Backup `
        -ControlCheckout $ControlCheckout `
        -CommandRunner $World.Runner `
        -CommandResolver $World.Resolver `
        -PortProbe $World.PortProbe `
        -ReleaseIdentityValidator $World.IdentityValidator
}

function Invoke-TestExpectedFailure {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Script,
        [Parameter(Mandatory = $true)]
        [string]$Pattern
    )

    $message = $null
    $threw = $false
    try {
        & $Script
    }
    catch {
        $threw = $true
        $message = [string]$_.Exception.Message
    }
    Assert-True -Condition $threw -Message "Expected failure matching /$Pattern/."
    Assert-True -Condition ($message -match $Pattern) -Message "Expected /$Pattern/, got: $message"
    return $message
}

function Get-TestGitVerb {
    param($Call)

    $args = @(Get-HermesGitArgsWithoutC -Arguments @($Call.Arguments))
    if ($args.Count -eq 0) {
        return ""
    }
    return [string]$args[0]
}

function Get-TestCallIndex {
    param(
        [Parameter(Mandatory = $true)]
        $Calls,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string]$Mode,
        [string]$GitVerb
    )

    for ($i = 0; $i -lt @($Calls).Count; $i++) {
        $call = @($Calls)[$i]
        if ([string]$call.Name -eq $Name) {
            if (
                ([string]::IsNullOrWhiteSpace($Mode) -or @($call.Arguments) -contains ("-$Mode")) -and
                ([string]::IsNullOrWhiteSpace($GitVerb) -or (Get-TestGitVerb -Call $call) -eq $GitVerb)
            ) {
                return $i
            }
        }
    }
    return -1
}

function Assert-NoStableMutation {
    param(
        [Parameter(Mandatory = $true)]
        $World,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Assert-Equal -Expected $World.State.CurrentSha -Actual $World.State.StableHead -Label "$Label HEAD"
    $switches = @($World.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "switch" })
    Assert-Equal -Expected 0 -Actual $switches.Count -Label "$Label switch count"
    $prepares = @($World.State.Calls | Where-Object { $_.Name -eq "powershell.exe" })
    Assert-Equal -Expected 0 -Actual $prepares.Count -Label "$Label Prepare/Validate count"
}

function Assert-NoForbiddenUpdateCommands {
    param(
        [Parameter(Mandatory = $true)]
        $World
    )

    foreach ($call in @($World.State.Calls)) {
        if ($call.Name -ne "git") {
            continue
        }
        $verb = Get-TestGitVerb -Call $call
        Assert-True -Condition (@("push", "pull", "checkout", "reset", "merge", "rebase", "tag") -notcontains $verb) -Message "Forbidden Git command was invoked: $verb"
    }
}

function Invoke-TestCase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Body
    )

    try {
        & $Body
        $script:Passed++
        Write-Host "PASS $Name" -ForegroundColor Green
    }
    catch {
        $script:Failed++
        Write-Host "FAIL $Name" -ForegroundColor Red
        Write-Host "     $($_.Exception.Message)" -ForegroundColor Red
    }
}

Invoke-TestCase "PowerShell 5.1 parser and no publication/start surface" {
    foreach ($path in @(
        (Join-Path $scriptRoot "update-stable.ps1"),
        (Join-Path $scriptRoot "update-stable-lib.ps1")
    )) {
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
        Assert-Equal -Expected 0 -Actual $errors.Count -Label "parser errors for $path"
    }
    $source = Get-Content -Raw (Join-Path $scriptRoot "update-stable-lib.ps1")
    Assert-True -Condition ($source -notmatch "gh\s+release\s+create") -Message "Update must not publish a GitHub Release."
    Assert-True -Condition ($source -notmatch '"(push|pull|checkout|reset|merge|rebase|tag)"') -Message "Update must not publish or rollback through Git."
    Assert-True -Condition ($source -notmatch "start-local|alembic\s+(upgrade|downgrade)") -Message "Update must not start Hermes or run migrations."
}

Invoke-TestCase "malformed target fails before backup or mutation" {
    $world = New-TestWorld
    Invoke-TestExpectedFailure -Pattern "Malformed version" -Script {
        Invoke-TestUpdate -World $world -TargetVersion "latest" | Out-Null
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "malformed target command count"
    Assert-NoStableMutation -World $world -Label "malformed target"
}

Invoke-TestCase "mutable Stable checkout cannot also be the control checkout" {
    $world = New-TestWorld
    Invoke-TestExpectedFailure -Pattern "Control checkout must be separate" -Script {
        Invoke-TestUpdate -World $world -ControlCheckout $world.State.Stable | Out-Null
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "same checkout command count"
}

Invoke-TestCase "dirty current Stable fails before backup or mutation" {
    $world = New-TestWorld -Status " M synthetic.txt"
    Invoke-TestExpectedFailure -Pattern "uncommitted or untracked" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-NoStableMutation -World $world -Label "dirty Stable"
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "dirty Stable backup count"
}

Invoke-TestCase "off-release current Stable fails before backup or mutation" {
    $world = New-TestWorld -CurrentTags @()
    Invoke-TestExpectedFailure -Pattern "not an immutable" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-NoStableMutation -World $world -Label "off-release Stable"
}

Invoke-TestCase "wrong origin fails closed" {
    $world = New-TestWorld -WrongOrigin
    Invoke-TestExpectedFailure -Pattern "does not point to LTstripes/hermes-finance" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "wrong origin backup count"
    Assert-NoStableMutation -World $world -Label "wrong origin"
}

Invoke-TestCase "running or occupied Stable runtime fails before backup" {
    $world = New-TestWorld -Occupied
    Invoke-TestExpectedFailure -Pattern "port 8000 is occupied" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "occupied backup count"
    Assert-NoStableMutation -World $world -Label "occupied Stable"
}

Invoke-TestCase "lightweight target tag fails before backup" {
    $world = New-TestWorld -TargetUnannotated
    Invoke-TestExpectedFailure -Pattern "not an annotated tag" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "lightweight target backup count"
    Assert-NoStableMutation -World $world -Label "lightweight target"
}

foreach ($case in @(
    @{ Name = "draft target release fails before backup"; Switch = "TargetDraft"; Pattern = "draft GitHub Release" },
    @{ Name = "prerelease target release fails before backup"; Switch = "TargetPrerelease"; Pattern = "prerelease GitHub Release" },
    @{ Name = "missing target release fails before backup"; Switch = "TargetMissing"; Pattern = "not a published GitHub Release" },
    @{ Name = "target release tag mismatch fails before backup"; Switch = "TargetReleaseTagMismatch"; Pattern = "does not match" }
)) {
    Invoke-TestCase $case.Name {
        $parameters = @{}
        $parameters[$case.Switch] = $true
        $world = New-TestWorld @parameters
        Invoke-TestExpectedFailure -Pattern $case.Pattern -Script {
            Invoke-TestUpdate -World $world | Out-Null
        } | Out-Null
        Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "$($case.Name) backup count"
        Assert-NoStableMutation -World $world -Label $case.Name
    }
}

Invoke-TestCase "downgrade fails before backup" {
    $world = New-TestWorld -CurrentVersion "0.8.4" -TargetVersion "0.8.3"
    Invoke-TestExpectedFailure -Pattern "downgrade is out of scope" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "downgrade backup count"
    Assert-NoStableMutation -World $world -Label "downgrade"
}

Invoke-TestCase "already-at-target is an explicit no-op" {
    $world = New-TestWorld -CurrentVersion "0.8.3" -TargetVersion "0.8.3" -LocalTargetAlreadyPresent
    $result = Invoke-TestUpdate -World $world
    Assert-Equal -Expected "no-op" -Actual $result.Status -Label "no-op status"
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "no-op backup count"
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "powershell.exe" }).Count -Label "no-op Prepare/Validate count"
    Assert-NoStableMutation -World $world -Label "no-op"
}

Invoke-TestCase "backup failure leaves Stable identity unchanged" {
    $world = New-TestWorld -BackupFailure
    $message = Invoke-TestExpectedFailure -Pattern "verified-backup|backup failed|synthetic backup failure" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "stable-checkout-unchanged") -Message "Backup failure must report unchanged Stable checkout."
    Assert-NoStableMutation -World $world -Label "backup failure"
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "fetch" }).Count -Label "backup failure fetch count"
}

Invoke-TestCase "fetch failure leaves a verified backup without switching Stable" {
    $world = New-TestWorld -FetchFailure
    $message = Invoke-TestExpectedFailure -Pattern "backup-verified-checkout-not-switched" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "auto-start=not-attempted") -Message "Fetch failure must not auto-start."
    Assert-Equal -Expected $world.State.CurrentSha -Actual $world.State.StableHead -Label "fetch failure HEAD"
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "switch" }).Count -Label "fetch failure switch count"
    Assert-True -Condition (Test-Path -LiteralPath $world.State.Backup -PathType Container) -Message "Fetch failure must retain the verified backup."
    Assert-Equal -Expected 0 -Actual $world.State.PrepareCalls -Label "fetch failure Prepare count"
}

Invoke-TestCase "exact fetch/tag proof followed by switch failure is not success" {
    $world = New-TestWorld -SwitchFailure
    $message = Invoke-TestExpectedFailure -Pattern "checkout-switch-not-proven|checkout-switch" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "rollback=not-attempted") -Message "Switch failure must not invent rollback."
    Assert-Equal -Expected 1 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "fetch" }).Count -Label "switch failure fetch count"
    Assert-Equal -Expected $world.State.CurrentSha -Actual $world.State.StableHead -Label "switch failure HEAD"
    Assert-Equal -Expected 1 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "switch" }).Count -Label "switch failure switch count"
    Assert-Equal -Expected 0 -Actual $world.State.PrepareCalls -Label "switch failure Prepare count"
}

Invoke-TestCase "target tag commit with mismatched release code fails before switch" {
    $world = New-TestWorld -TargetProjectVersion "0.8.2"
    $message = Invoke-TestExpectedFailure -Pattern "requested project version" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "backup-verified-checkout-not-switched") -Message "Target identity failure must expose verified backup and no switch."
    Assert-True -Condition (Test-Path -LiteralPath $world.State.Backup -PathType Container) -Message "Successful backup proof must exist before target identity failure."
    Assert-NoStableMutation -World $world -Label "target code mismatch"
}

Invoke-TestCase "runtime/data collision fails closed and never overwrites" {
    $world = New-TestWorld -TargetTreePaths @(
        "data/.gitkeep",
        "data/finance.db",
        "backend/pyproject.toml",
        "backend/src/hermes_finance/__init__.py",
        "docs/release-notes-0.8.3.md",
        "scripts/prepare-runtime.ps1"
    )
    $databaseBefore = [IO.File]::ReadAllBytes($world.State.Database)
    Invoke-TestExpectedFailure -Pattern "production-data path|configured Stable database path" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-NoStableMutation -World $world -Label "runtime collision"
    Assert-Equal -Expected 0 -Actual $world.State.PrepareCalls -Label "runtime collision Prepare count"
    Assert-True -Condition ([Convert]::ToBase64String($databaseBefore) -eq [Convert]::ToBase64String([IO.File]::ReadAllBytes($world.State.Database))) -Message "Runtime collision must not change the synthetic database."
}

Invoke-TestCase "existing ignored runtime collision fails closed" {
    $world = New-TestWorld `
        -TargetTreePaths @(
            "data/.gitkeep",
            "backend/pyproject.toml",
            "backend/src/hermes_finance/__init__.py",
            "docs/release-notes-0.8.3.md",
            "scripts/prepare-runtime.ps1",
            "frontend/local-runtime/report.txt"
        ) `
        -IgnoredPaths @("data/finance.db", "frontend/local-runtime") `
        -SwitchIgnoredCollision
    $message = Invoke-TestExpectedFailure -Pattern "checkout-switch-not-proven" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "rollback=not-attempted") -Message "Ignored collision must not invent rollback."
    Assert-Equal -Expected $world.State.CurrentSha -Actual $world.State.StableHead -Label "ignored runtime collision HEAD"
    $switchCall = @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "switch" })[0]
    Assert-True -Condition ($null -ne $switchCall) -Message "Ignored collision must reach the protected switch operation."
    Assert-True -Condition (@($switchCall.Arguments) -contains "--no-overwrite-ignore") -Message "Stable switch must protect existing ignored files."
    Assert-Equal -Expected 0 -Actual $world.State.PrepareCalls -Label "ignored runtime collision Prepare count"
}

Invoke-TestCase "current tracked production data fails before backup" {
    $world = New-TestWorld -CurrentTrackedPaths @(
        "data/.gitkeep",
        "data/finance.db",
        "backend/pyproject.toml",
        "backend/src/hermes_finance/__init__.py",
        "docs/release-notes-0.8.2.md",
        "scripts/prepare-runtime.ps1"
    )
    Invoke-TestExpectedFailure -Pattern "Current Stable checkout contains a tracked production-data path" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    } | Out-Null
    Assert-NoStableMutation -World $world -Label "current tracked production data"
    Assert-Equal -Expected 0 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "python" }).Count -Label "current tracked production data backup count"
}

Invoke-TestCase "successful update proves order, target Prepare/Validate and untouched unrelated path" {
    $world = New-TestWorld
    $previewCheckout = Join-Path $world.State.Root "Preview Checkout"
    New-Item -ItemType Directory -Force -Path $previewCheckout | Out-Null
    $previewMarker = Join-Path $previewCheckout "preview marker"
    Write-Utf8NoBom -Path $previewMarker -Content "synthetic untouched marker`n"
    $beforePreview = Get-Content -Raw $previewMarker
    $result = Invoke-TestUpdate -World $world

    Assert-Equal -Expected "updated" -Actual $result.Status -Label "successful update status"
    Assert-Equal -Expected $world.State.TargetSha -Actual $world.State.StableHead -Label "successful target HEAD"
    Assert-Equal -Expected 1 -Actual $world.State.PrepareCalls -Label "successful Prepare count"
    Assert-Equal -Expected 1 -Actual $world.State.ValidateCalls -Label "successful Validate count"
    Assert-Equal -Expected 2 -Actual $world.State.IdentityCalls -Label "successful identity proof count"
    Assert-True -Condition (Test-Path -LiteralPath $world.State.Backup -PathType Container) -Message "Successful update must create the backup directory."
    Assert-True -Condition (@(Get-ChildItem -LiteralPath $world.State.Backup -File -Filter "finance_backup_*.sqlite3").Count -eq 1) -Message "Successful update must create one synthetic SQLite backup."
    $expectedPrepareCalls = "Prepare{0}Validate{0}" -f [Environment]::NewLine
    Assert-Equal -Expected $expectedPrepareCalls -Actual (Get-Content -Raw (Join-Path $world.State.Stable "target-prepare-calls.log")) -Label "target Prepare/Validate calls"
    Assert-Equal -Expected $beforePreview -Actual (Get-Content -Raw $previewMarker) -Label "unrelated marker"

    $backupAt = Get-TestCallIndex -Calls $world.State.Calls -Name "python"
    $fetchAt = Get-TestCallIndex -Calls $world.State.Calls -Name "git" -GitVerb "fetch"
    $switchAt = Get-TestCallIndex -Calls $world.State.Calls -Name "git" -GitVerb "switch"
    $prepareAt = Get-TestCallIndex -Calls $world.State.Calls -Name "powershell.exe" -Mode "Prepare"
    $validateAt = Get-TestCallIndex -Calls $world.State.Calls -Name "powershell.exe" -Mode "Validate"
    Assert-True -Condition ($backupAt -ge 0 -and $fetchAt -gt $backupAt -and $switchAt -gt $fetchAt -and $prepareAt -gt $switchAt -and $validateAt -gt $prepareAt) -Message "Required order is prove -> backup -> fetch -> switch -> Prepare -> Validate."

    $fetchCall = @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "fetch" })[0]
    $fetchArgs = @(Get-HermesGitArgsWithoutC -Arguments @($fetchCall.Arguments))
    Assert-True -Condition ($fetchArgs -contains "--no-tags") -Message "Target fetch must disable automatic tag discovery."
    Assert-True -Condition ($fetchArgs -contains "origin") -Message "Target fetch must use named origin."
    Assert-True -Condition ($fetchArgs -contains "refs/tags/v0.8.3:refs/tags/v0.8.3") -Message "Target fetch must name only the explicit release tag."
    Assert-True -Condition (@($fetchArgs | Where-Object { [string]$_ -match "refs/heads|main|latest" }).Count -eq 0) -Message "Target fetch must not follow a branch or latest."

    foreach ($call in @($world.State.Calls | Where-Object { $_.Name -eq "powershell.exe" })) {
        Assert-True -Condition (@($call.Arguments) -contains "-Checkout") -Message "Target Prepare/Validate must receive an explicit checkout."
        $checkoutArg = Get-TestFlagValue -Arguments @($call.Arguments) -Flag "-Checkout"
        Assert-Equal -Expected $world.State.Stable -Actual $checkoutArg -Label "target checkout argument"
        Assert-True -Condition (@($call.Arguments) -notcontains "-Repair") -Message "OPS02 must not expose recovery/repair mode."
    }
    Assert-NoForbiddenUpdateCommands -World $world
}

Invoke-TestCase "Prepare failure leaves target pinned but visibly unprepared without rollback" {
    $world = New-TestWorld -PrepareFailure
    $message = Invoke-TestExpectedFailure -Pattern "target-pinned-but-unprepared" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "rollback=not-attempted") -Message "Prepare failure must state rollback was not attempted."
    Assert-True -Condition ($message -match "auto-start=not-attempted") -Message "Prepare failure must state auto-start was not attempted."
    Assert-Equal -Expected $world.State.TargetSha -Actual $world.State.StableHead -Label "Prepare failure target HEAD"
    Assert-Equal -Expected 1 -Actual $world.State.PrepareCalls -Label "Prepare failure Prepare count"
    Assert-Equal -Expected 0 -Actual $world.State.ValidateCalls -Label "Prepare failure Validate count"
    Assert-Equal -Expected 1 -Actual @($world.State.Calls | Where-Object { $_.Name -eq "git" -and (Get-TestGitVerb -Call $_) -eq "switch" }).Count -Label "Prepare failure switch count"
    Assert-NoForbiddenUpdateCommands -World $world
}

Invoke-TestCase "Validate failure leaves target pinned and does not auto-start or rollback" {
    $world = New-TestWorld -ValidateFailure
    $message = Invoke-TestExpectedFailure -Pattern "target-pinned-but-unprepared" -Script {
        Invoke-TestUpdate -World $world | Out-Null
    }
    Assert-True -Condition ($message -match "db-migration=not-attempted") -Message "Validate failure must state migration was not attempted."
    Assert-Equal -Expected $world.State.TargetSha -Actual $world.State.StableHead -Label "Validate failure target HEAD"
    Assert-Equal -Expected 1 -Actual $world.State.PrepareCalls -Label "Validate failure Prepare count"
    Assert-Equal -Expected 1 -Actual $world.State.ValidateCalls -Label "Validate failure Validate count"
    Assert-NoForbiddenUpdateCommands -World $world
}

try {
    Write-Host ""
    Write-Host "Stable update synthetic regressions: $script:Passed passed, $script:Failed failed."
    if ($script:Failed -ne 0) {
        exit 1
    }
}
finally {
    foreach ($root in @($script:TempRoots)) {
        if (Test-Path -LiteralPath $root) {
            Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
