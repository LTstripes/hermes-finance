# Focused real-Git synthetic integration smoke for the explicit Stable update.
# The GitHub Release lookup is injected, but the temporary repositories,
# annotated tags, fetch, protected switch, backup and target Prepare/Validate
# all use the existing production operation and native tools.

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
$script:GitExecutable = (Get-Command "git.exe" -ErrorAction Stop).Source
$script:PowerShellExecutable = (Get-Command "powershell.exe" -ErrorAction Stop).Source
$script:CanonicalUrl = "https://github.com/LTstripes/hermes-finance.git"

$pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
$script:UvExecutable = (Get-Command "uv.exe" -ErrorAction SilentlyContinue).Source
if ($null -ne $pythonCommand) {
    $script:PythonExecutable = $pythonCommand.Source
    $script:PythonUsesUv = $false
}
elseif (-not [string]::IsNullOrWhiteSpace($script:UvExecutable)) {
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
    throw "Real-Git Stable update smoke requires python.exe or uv.exe."
}

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

function Invoke-SyntheticGit {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $result = Invoke-HermesNativeCommand -FileName $script:GitExecutable -ArgumentList @($Arguments)
    if (-not $AllowFailure -and [int]$result.ExitCode -ne 0) {
        $detail = [string]$result.Stderr
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = [string]$result.Stdout
        }
        throw "Synthetic Git command failed (exit $($result.ExitCode)): git $([string]::Join(' ', @($Arguments)))`n$detail"
    }

    return $result
}

function Invoke-SyntheticPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $effectiveArguments = @($Arguments)
    if ($script:PythonUsesUv) {
        $effectiveArguments = @("run", "python") + @($Arguments)
    }
    $result = Invoke-HermesNativeCommand -FileName $script:PythonExecutable -ArgumentList $effectiveArguments
    if ([int]$result.ExitCode -ne 0) {
        $detail = [string]$result.Stderr
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = [string]$result.Stdout
        }
        throw "Synthetic Python command failed (exit $($result.ExitCode)): $detail"
    }

    return $result
}

function New-SyntheticTargetPrepareScript {
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

function New-SyntheticVersionFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    Write-Utf8NoBom `
        -Path (Join-Path $Checkout "backend/pyproject.toml") `
        -Content ('[project]' + [Environment]::NewLine + 'version = "' + $Version + '"' + [Environment]::NewLine)
    Write-Utf8NoBom `
        -Path (Join-Path $Checkout "backend/src/hermes_finance/__init__.py") `
        -Content ('__version__ = "' + $Version + '"' + [Environment]::NewLine)
    Write-Utf8NoBom `
        -Path (Join-Path $Checkout ("docs/release-notes-{0}.md" -f $Version)) `
        -Content ("Synthetic release notes for {0}.`n" -f $Version)
}

function New-RealGitFixture {
    param(
        [switch]$IgnoredCollision
    )

    $root = Join-Path ([IO.Path]::GetTempPath()) ("hermes r09 ops02 real git " + [guid]::NewGuid().ToString("N"))
    [void]$script:TempRoots.Add($root)
    $bare = Join-Path $root "synthetic remote.git"
    $seed = Join-Path $root "release seed"
    $stable = Join-Path $root "Stable Checkout With Spaces"
    $control = Join-Path $root "trusted control checkout"
    $database = Join-Path $stable "data/finance.db"
    $backup = Join-Path $stable "data/backups"
    $currentVersion = "0.8.2"
    $targetVersion = "0.8.3"
    $currentTag = "v$currentVersion"
    $targetTag = "v$targetVersion"

    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Invoke-SyntheticGit -Arguments @("init", "--bare", $bare) | Out-Null
    Invoke-SyntheticGit -Arguments @("init", $seed) | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $seed, "config", "user.name", "Hermes Synthetic") | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $seed, "config", "user.email", "synthetic@example.invalid") | Out-Null

    New-Item -ItemType Directory -Force -Path @(
        (Join-Path $seed "backend/src/hermes_finance"),
        (Join-Path $seed "docs"),
        (Join-Path $seed "scripts"),
        (Join-Path $seed "data"),
        (Join-Path $control "scripts")
    ) | Out-Null
    Write-Utf8NoBom -Path (Join-Path $seed ".gitignore") -Content @'
data/*
!data/.gitkeep
target-prepare-calls.log
.synthetic-target-prepared
frontend/local-runtime/
'@
    New-Item -ItemType File -Force -Path (Join-Path $seed "data/.gitkeep") | Out-Null
    New-SyntheticTargetPrepareScript -Path (Join-Path $seed "scripts/prepare-runtime.ps1")
    New-SyntheticVersionFiles -Checkout $seed -Version $currentVersion
    Invoke-SyntheticGit -Arguments @("-C", $seed, "add", "-A") | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $seed, "commit", "-m", "Synthetic release $currentTag") | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $seed, "tag", "-a", $currentTag, "-m", "Synthetic annotated $currentTag") | Out-Null
    $currentCommit = ([string](Invoke-SyntheticGit -Arguments @("-C", $seed, "rev-parse", "HEAD")).Stdout).Trim().ToLowerInvariant()

    Remove-Item -LiteralPath (Join-Path $seed ("docs/release-notes-{0}.md" -f $currentVersion)) -Force
    New-SyntheticVersionFiles -Checkout $seed -Version $targetVersion
    if ($IgnoredCollision) {
        $collisionPath = Join-Path $seed "frontend/local-runtime/report.txt"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $collisionPath) | Out-Null
        Write-Utf8NoBom -Path $collisionPath -Content "target release collision`n"
        Invoke-SyntheticGit -Arguments @("-C", $seed, "add", "-f", "frontend/local-runtime/report.txt") | Out-Null
    }
    Invoke-SyntheticGit -Arguments @("-C", $seed, "add", "-A") | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $seed, "commit", "-m", "Synthetic release $targetTag") | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $seed, "tag", "-a", $targetTag, "-m", "Synthetic annotated $targetTag") | Out-Null
    $targetCommit = ([string](Invoke-SyntheticGit -Arguments @("-C", $seed, "rev-parse", "HEAD")).Stdout).Trim().ToLowerInvariant()
    Invoke-SyntheticGit -Arguments @(
        "-C", $seed,
        "push", $bare,
        "HEAD:refs/heads/main",
        $currentTag,
        $targetTag
    ) | Out-Null

    New-Item -ItemType Directory -Force -Path $stable | Out-Null
    Invoke-SyntheticGit -Arguments @("init", $stable) | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $stable, "remote", "add", "origin", $bare) | Out-Null
    Invoke-SyntheticGit -Arguments @(
        "-C", $stable,
        "fetch", "--no-tags", "origin",
        ("refs/tags/{0}:refs/tags/{0}" -f $currentTag)
    ) | Out-Null
    Invoke-SyntheticGit -Arguments @("-C", $stable, "switch", "--detach", $currentCommit) | Out-Null

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $database) | Out-Null
    Invoke-SyntheticPython -Arguments @(
        "-c",
        "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('create table synthetic_marker (value text)'); db.execute('insert into synthetic_marker values (?)', ('temp-only',)); db.commit(); db.close()",
        $database
    ) | Out-Null
    Copy-Item `
        -LiteralPath (Join-Path $scriptRoot "launcher-production-backup.py") `
        -Destination (Join-Path $control "scripts/launcher-production-backup.py")

    if ($IgnoredCollision) {
        $collisionPath = Join-Path $stable "frontend/local-runtime/report.txt"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $collisionPath) | Out-Null
        Write-Utf8NoBom -Path $collisionPath -Content "private synthetic collision`n"
        $ignored = Invoke-SyntheticGit -Arguments @(
            "-C", $stable, "check-ignore", "--quiet", "--", "frontend/local-runtime/report.txt"
        ) -AllowFailure
        Assert-Equal -Expected 0 -Actual $ignored.ExitCode -Label "synthetic collision ignored-file proof"
    }

    $fixture = [pscustomobject]@{
        Root             = $root
        Bare             = $bare
        Seed             = $seed
        Stable           = $stable
        Control          = $control
        Database         = $database
        Backup           = $backup
        CanonicalUrl     = $script:CanonicalUrl
        CurrentVersion   = $currentVersion
        TargetVersion    = $targetVersion
        CurrentTag       = $currentTag
        TargetTag        = $targetTag
        CurrentCommit    = $currentCommit
        TargetCommit     = $targetCommit
        IgnoredCollision = [bool]$IgnoredCollision
        Calls            = New-Object System.Collections.ArrayList
    }

    $runner = {
        param($Request)

        $arguments = @($Request.Arguments)
        [void]$fixture.Calls.Add([pscustomobject]@{
                Name      = [string]$Request.Name
                FileName  = [string]$Request.FileName
                Arguments = $arguments
            })

        if ([string]$Request.Name -eq "gh") {
            $apiPath = [string](@(
                    $arguments |
                        Where-Object { [string]$_ -like "repos/LTstripes/hermes-finance/releases/tags/*" } |
                        Select-Object -First 1
                ))
            if ([string]::IsNullOrWhiteSpace($apiPath)) {
                throw "Real-Git smoke received an unexpected GitHub API path."
            }
            $tag = $apiPath.Substring($apiPath.LastIndexOf("/") + 1)
            if ($tag -ne $fixture.CurrentTag -and $tag -ne $fixture.TargetTag) {
                return New-HermesCommandResult -ExitCode 1 -Stderr "Not Found (HTTP 404)"
            }
            $payload = @{
                tag_name   = $tag
                draft      = $false
                prerelease = $false
                html_url   = "https://github.com/LTstripes/hermes-finance/releases/tag/$tag"
            }
            return New-HermesCommandResult -Stdout ($payload | ConvertTo-Json -Compress)
        }

        if ([string]$Request.Name -eq "git") {
            $gitArgs = @(Get-HermesGitArgsWithoutC -Arguments $arguments)
            if (
                $gitArgs.Count -ge 2 -and
                [string]$gitArgs[0] -eq "remote" -and
                [string]$gitArgs[1] -eq "get-url"
            ) {
                # The real remote is a temp bare repository; only the
                # repository-identity proof is injected so the production
                # GitHub URL guard can remain unchanged.
                return New-HermesCommandResult -Stdout $fixture.CanonicalUrl
            }
        }

        return Invoke-HermesNativeCommand -FileName ([string]$Request.FileName) -ArgumentList $arguments
    }.GetNewClosure()

    $gitExecutable = [string]$script:GitExecutable
    $pythonExecutable = [string]$script:PythonExecutable
    $powerShellExecutable = [string]$script:PowerShellExecutable
    $resolver = {
        param([string]$Name)
        switch ($Name) {
            "git" { return $gitExecutable }
            "gh" { return "synthetic-gh.exe" }
            "python.exe" { return $pythonExecutable }
            "powershell.exe" { return $powerShellExecutable }
            default { return $null }
        }
    }.GetNewClosure()

    $portProbe = {
        param([string]$Checkout)
        return $true
    }.GetNewClosure()

    $fixture | Add-Member -MemberType NoteProperty -Name Runner -Value $runner
    $fixture | Add-Member -MemberType NoteProperty -Name Resolver -Value $resolver
    $fixture | Add-Member -MemberType NoteProperty -Name PortProbe -Value $portProbe
    return $fixture
}

function Get-RealGitVerb {
    param(
        [Parameter(Mandatory = $true)]
        $Call
    )

    $args = @(Get-HermesGitArgsWithoutC -Arguments @($Call.Arguments))
    if ($args.Count -eq 0) {
        return ""
    }
    return [string]$args[0]
}

function Get-RealCallIndex {
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
        if ([string]$call.Name -ne $Name) {
            continue
        }
        if (-not [string]::IsNullOrWhiteSpace($Mode) -and @($call.Arguments) -notcontains ("-$Mode")) {
            continue
        }
        if (-not [string]::IsNullOrWhiteSpace($GitVerb) -and (Get-RealGitVerb -Call $call) -ne $GitVerb) {
            continue
        }
        return $i
    }

    return -1
}

function Assert-RealAnnotatedTag {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$Tag,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommit
    )

    $type = ([string](Invoke-SyntheticGit -Arguments @(
                "-C", $Checkout, "cat-file", "-t", "refs/tags/$Tag"
            )).Stdout).Trim()
    Assert-Equal -Expected "tag" -Actual $type -Label "$Tag object type"
    $peeled = ([string](Invoke-SyntheticGit -Arguments @(
                "-C", $Checkout, "rev-parse", "--verify", "refs/tags/$Tag^{commit}"
            )).Stdout).Trim().ToLowerInvariant()
    Assert-Equal -Expected $ExpectedCommit -Actual $peeled -Label "$Tag peeled commit"
}

function Assert-RealDetachedHead {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommit
    )

    $head = ([string](Invoke-SyntheticGit -Arguments @(
                "-C", $Checkout, "rev-parse", "--verify", "HEAD"
            )).Stdout).Trim().ToLowerInvariant()
    Assert-Equal -Expected $ExpectedCommit -Actual $head -Label "real Stable HEAD"
    $symbolic = Invoke-SyntheticGit -Arguments @(
        "-C", $Checkout, "symbolic-ref", "--quiet", "--short", "HEAD"
    ) -AllowFailure
    Assert-True -Condition ([int]$symbolic.ExitCode -ne 0) -Message "Successful Stable update must leave detached HEAD."
}

function Invoke-RealExpectedFailure {
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
    Assert-True -Condition $threw -Message "Expected real-Git failure matching /$Pattern/."
    Assert-True -Condition ($message -match $Pattern) -Message "Expected /$Pattern/, got: $message"
    return $message
}

function Invoke-RealUpdate {
    param(
        [Parameter(Mandatory = $true)]
        $Fixture
    )

    return Invoke-HermesStableUpdate `
        -StableCheckout $Fixture.Stable `
        -TargetVersion $Fixture.TargetVersion `
        -DatabasePath $Fixture.Database `
        -BackupDirectory $Fixture.Backup `
        -ControlCheckout $Fixture.Control `
        -CommandRunner $Fixture.Runner `
        -CommandResolver $Fixture.Resolver `
        -PortProbe $Fixture.PortProbe
}

function Invoke-RealGitCase {
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

Invoke-RealGitCase "real-Git success proves annotated tags, exact fetch, detached switch and Prepare/Validate order" {
    $fixture = New-RealGitFixture
    Assert-RealAnnotatedTag `
        -Checkout $fixture.Stable `
        -Tag $fixture.CurrentTag `
        -ExpectedCommit $fixture.CurrentCommit
    $targetBeforeFetch = Invoke-SyntheticGit -Arguments @(
        "-C", $fixture.Stable, "show-ref", "--verify", "--quiet", "refs/tags/$($fixture.TargetTag)"
    ) -AllowFailure
    Assert-True -Condition ([int]$targetBeforeFetch.ExitCode -ne 0) -Message "Target tag must not be local before the explicit fetch."

    $result = Invoke-RealUpdate -Fixture $fixture
    Assert-Equal -Expected "updated" -Actual $result.Status -Label "real-Git success status"
    Assert-Equal -Expected $fixture.TargetCommit -Actual $result.TargetCommit -Label "real-Git target commit"
    Assert-RealAnnotatedTag `
        -Checkout $fixture.Stable `
        -Tag $fixture.TargetTag `
        -ExpectedCommit $fixture.TargetCommit
    Assert-RealDetachedHead -Checkout $fixture.Stable -ExpectedCommit $fixture.TargetCommit

    $status = ([string](Invoke-SyntheticGit -Arguments @(
                "-C", $fixture.Stable, "status", "--porcelain=v1", "--untracked-files=all"
            )).Stdout).Trim()
    Assert-True -Condition ([string]::IsNullOrWhiteSpace($status)) -Message "Successful real-Git update must leave the Stable checkout clean."
    $remotePeeled = ([string](Invoke-SyntheticGit -Arguments @(
                "-C", $fixture.Stable, "ls-remote", "--tags", "origin", "refs/tags/$($fixture.TargetTag)^{}"
            )).Stdout).Trim()
    Assert-True -Condition ($remotePeeled -match $fixture.TargetCommit) -Message "Target annotated tag must be proven from the local synthetic remote."

    $backupFiles = @(Get-ChildItem -LiteralPath $fixture.Backup -File -Filter "finance_backup_*.sqlite3")
    Assert-Equal -Expected 1 -Actual $backupFiles.Count -Label "real-Git verified backup count"
    Assert-True -Condition ($backupFiles[0].Length -gt 0) -Message "Real-Git success must retain a non-empty synthetic SQLite backup."
    $expectedPrepareCalls = "Prepare{0}Validate{0}" -f [Environment]::NewLine
    Assert-Equal `
        -Expected $expectedPrepareCalls `
        -Actual (Get-Content -Raw (Join-Path $fixture.Stable "target-prepare-calls.log")) `
        -Label "real-Git target Prepare/Validate calls"
    Assert-True -Condition (Test-Path -LiteralPath (Join-Path $fixture.Stable ".synthetic-target-prepared") -PathType Leaf) -Message "Real target Prepare must run before Validate."

    $backupAt = Get-RealCallIndex -Calls $fixture.Calls -Name "python"
    $fetchAt = Get-RealCallIndex -Calls $fixture.Calls -Name "git" -GitVerb "fetch"
    $switchAt = Get-RealCallIndex -Calls $fixture.Calls -Name "git" -GitVerb "switch"
    $prepareAt = Get-RealCallIndex -Calls $fixture.Calls -Name "powershell.exe" -Mode "Prepare"
    $validateAt = Get-RealCallIndex -Calls $fixture.Calls -Name "powershell.exe" -Mode "Validate"
    Assert-True `
        -Condition ($backupAt -ge 0 -and $fetchAt -gt $backupAt -and $switchAt -gt $fetchAt -and $prepareAt -gt $switchAt -and $validateAt -gt $prepareAt) `
        -Message "Real-Git order must be proof -> backup -> fetch -> switch -> Prepare -> Validate."

    $fetchCall = @($fixture.Calls | Where-Object { $_.Name -eq "git" -and (Get-RealGitVerb -Call $_) -eq "fetch" })[0]
    $fetchArgs = @(Get-HermesGitArgsWithoutC -Arguments @($fetchCall.Arguments))
    Assert-True -Condition (@($fetchArgs) -contains "--no-tags") -Message "Real target fetch must disable automatic tag discovery."
    Assert-True -Condition (@($fetchArgs) -contains ("refs/tags/{0}:refs/tags/{0}" -f $fixture.TargetTag)) -Message "Real target fetch must name only the explicit release tag."

    $switchCall = @($fixture.Calls | Where-Object { $_.Name -eq "git" -and (Get-RealGitVerb -Call $_) -eq "switch" })[0]
    $switchArgs = @(Get-HermesGitArgsWithoutC -Arguments @($switchCall.Arguments))
    Assert-True -Condition (@($switchArgs) -contains "--no-overwrite-ignore") -Message "Real Stable switch must protect ignored files."
    Assert-True -Condition (@($switchArgs) -contains $fixture.TargetCommit) -Message "Real Stable switch must target the proven commit, not a branch or latest selector."

    foreach ($call in @($fixture.Calls | Where-Object { $_.Name -eq "powershell.exe" })) {
        Assert-True -Condition (@($call.Arguments) -contains "-Checkout") -Message "Real target Prepare/Validate must receive an explicit checkout."
        $checkoutIndex = [array]::IndexOf(@($call.Arguments), "-Checkout")
        Assert-Equal -Expected $fixture.Stable -Actual ([string]$call.Arguments[$checkoutIndex + 1]) -Label "real target checkout argument"
    }
}

Invoke-RealGitCase "real-Git ignored collision preserves private file and fails closed before Prepare/Validate" {
    $fixture = New-RealGitFixture -IgnoredCollision
    $collisionPath = Join-Path $fixture.Stable "frontend/local-runtime/report.txt"
    $beforeCollision = [IO.File]::ReadAllText($collisionPath)
    $message = Invoke-RealExpectedFailure -Pattern "checkout-switch-not-proven" -Script {
        Invoke-RealUpdate -Fixture $fixture | Out-Null
    }
    Assert-True -Condition ($message -match "rollback=not-attempted") -Message "Real ignored collision must not invent rollback."

    $head = ([string](Invoke-SyntheticGit -Arguments @(
                "-C", $fixture.Stable, "rev-parse", "--verify", "HEAD"
            )).Stdout).Trim().ToLowerInvariant()
    Assert-Equal -Expected $fixture.CurrentCommit -Actual $head -Label "real ignored collision HEAD"
    Assert-Equal -Expected $beforeCollision -Actual ([IO.File]::ReadAllText($collisionPath)) -Label "ignored collision content"
    Assert-RealAnnotatedTag `
        -Checkout $fixture.Stable `
        -Tag $fixture.TargetTag `
        -ExpectedCommit $fixture.TargetCommit

    $backupFiles = @(Get-ChildItem -LiteralPath $fixture.Backup -File -Filter "finance_backup_*.sqlite3")
    Assert-Equal -Expected 1 -Actual $backupFiles.Count -Label "ignored collision verified backup count"
    Assert-True -Condition ($backupFiles[0].Length -gt 0) -Message "Ignored collision must fail after retaining the verified backup."
    Assert-Equal -Expected 0 -Actual @($fixture.Calls | Where-Object { $_.Name -eq "powershell.exe" }).Count -Label "ignored collision Prepare/Validate count"
    $switchCall = @($fixture.Calls | Where-Object { $_.Name -eq "git" -and (Get-RealGitVerb -Call $_) -eq "switch" })[0]
    $switchArgs = @(Get-HermesGitArgsWithoutC -Arguments @($switchCall.Arguments))
    Assert-True -Condition (@($switchArgs) -contains "--no-overwrite-ignore") -Message "Ignored collision must reach real protected switch."
}

try {
    Write-Host ""
    Write-Host "Stable update real-Git integration smoke: $script:Passed passed, $script:Failed failed."
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
