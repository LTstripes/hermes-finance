# Deterministic local tests for the guarded Windows release helper.
# Uses a fake command runner. Never creates a real tag or GitHub Release.

[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$libraryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\release-lib.ps1"))
if (-not (Test-Path -LiteralPath $libraryPath -PathType Leaf)) {
    throw "release-lib.ps1 not found at '$libraryPath'."
}
. $libraryPath

$script:Passed = 0
$script:Failed = 0
$script:TempRoots = New-Object System.Collections.ArrayList
$script:ExpectedSha = "0123456789abcdef0123456789abcdef01234567"
$script:OtherSha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
$script:TagName = "v0.5.0"
$script:CanonicalUrl = "https://github.com/LTstripes/hermes-finance.git"

function New-CyrillicToken {
    param([Parameter(Mandatory = $true)][string]$Which)

    switch ($Which) {
        "test" { return -join @([char]0x0442, [char]0x0435, [char]0x0441, [char]0x0442) }
        "notes" { return -join @([char]0x0437, [char]0x0430, [char]0x043C, [char]0x0435, [char]0x0442, [char]0x043A, [char]0x0438) }
        default { throw "Unknown Cyrillic token '$Which'." }
    }
}

function New-HermesTestJson {
    param($Object)

    if ($null -eq $Object) {
        return "[]"
    }

    $items = @($Object)
    if ($items.Count -eq 0) {
        return "[]"
    }
    if ($items.Count -eq 1) {
        return "[" + ($items[0] | ConvertTo-Json -Compress -Depth 6) + "]"
    }

    return $items | ConvertTo-Json -Compress -Depth 6
}

function New-FakeTagObjectSha {
    param([Parameter(Mandatory = $true)][string]$CommitSha)

    if ($CommitSha.Substring(0, 1) -eq "0") {
        return "f" + $CommitSha.Substring(1)
    }

    return "0" + $CommitSha.Substring(1)
}

function Get-RequestFlagValue {
    param(
        [string[]]$Arguments,
        [string]$Flag
    )

    $items = @($Arguments)
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($items[$i] -eq $Flag -and ($i + 1) -lt $items.Count) {
            return [string]$items[$i + 1]
        }
    }

    return $null
}

function New-HermesTestWorkspace {
    param([switch]$CyrillicNotes)

    $suffix = [guid]::NewGuid().ToString("N")
    $rootName = "hermes-m04-01-$suffix"
    if ($CyrillicNotes) {
        $rootName = "hermes m04-01 " + (New-CyrillicToken -Which "test") + " $suffix"
    }

    $root = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) $rootName))
    New-Item -ItemType Directory -Path $root | Out-Null
    New-Item -ItemType File -Path (Join-Path $root ".git") | Out-Null
    [void]$script:TempRoots.Add($root)

    $notesName = "notes.md"
    if ($CyrillicNotes) {
        $notesName = (New-CyrillicToken -Which "notes") + " 0.5.0.md"
    }
    $notesPath = Join-Path $root $notesName
    [IO.File]::WriteAllText($notesPath, "Synthetic release notes for tests.`n", (New-Object System.Text.UTF8Encoding $false))

    return [pscustomobject]@{
        RepoRoot  = $root
        NotesPath = $notesPath
    }
}

function New-SuccessfulCiRun {
    param([string]$Sha = $script:ExpectedSha)

    return @{
        databaseId   = 11
        headSha      = $Sha
        status       = "completed"
        conclusion   = "success"
        event        = "push"
        headBranch   = "main"
        workflowName = "CI"
        url          = "https://github.com/LTstripes/hermes-finance/actions/runs/11"
        name         = "CI"
    }
}

function New-HermesFakeWorld {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [string]$ExpectedSha = $script:ExpectedSha,
        [string]$OriginMain = $script:ExpectedSha,
        [string]$OriginUrl = $script:CanonicalUrl,
        $FetchUrls = $null,
        $PushUrls = $null,
        $Mirror = $null,
        $LocalTag = $null,
        $RemoteTag = $null,
        $Release = $null,
        $CiRuns = $null,
        [int]$GhAuthExit = 0,
        [int]$LsRemoteExit = 0,
        [string]$ReleaseApiFailure = "",
        [switch]$FailReleaseCreate,
        [switch]$FailPush
    )

    if ($null -eq $CiRuns) {
        $CiRuns = @(New-SuccessfulCiRun -Sha $ExpectedSha)
    }
    if ($null -eq $FetchUrls) {
        $FetchUrls = @($OriginUrl)
    }

    $state = @{
        RepoRoot          = $RepoRoot
        ExpectedSha       = $ExpectedSha
        OriginMain        = $OriginMain
        FetchUrls         = @($FetchUrls)
        PushUrls          = $PushUrls
        Mirror            = $Mirror
        Fetched           = $false
        LocalTag          = $LocalTag
        RemoteTag         = $RemoteTag
        Release           = $Release
        CiRuns            = @($CiRuns)
        GhAuthExit        = $GhAuthExit
        LsRemoteExit      = [int]$LsRemoteExit
        ReleaseApiFailure = [string]$ReleaseApiFailure
        FailReleaseCreate = [bool]$FailReleaseCreate
        FailPush          = [bool]$FailPush
        Calls             = New-Object System.Collections.ArrayList
        DeletedTag        = $false
        ForcedTag         = $false
    }

    $runner = {
        param($Request)

        $name = [string]$Request.Name
        $arguments = @($Request.Arguments)
        [void]$state.Calls.Add(
            [pscustomobject]@{
                Name      = $name
                Arguments = $arguments
            }
        )

        if ($name -eq "git") {
            return Invoke-FakeGitCommand -State $state -Arguments $arguments
        }
        if ($name -eq "gh") {
            return Invoke-FakeGhCommand -State $state -Arguments $arguments
        }

        throw "Unexpected tool '$name'. The release helper must not call anything except git and gh."
    }.GetNewClosure()

    return [pscustomobject]@{
        State  = $state
        Runner = $runner
    }
}

function Invoke-FakeGitCommand {
    param($State, [string[]]$Arguments)

    $gitArgs = @(Get-HermesGitArgsWithoutC -Arguments $Arguments)
    if ($gitArgs.Count -eq 0) {
        throw "Fake git received no arguments."
    }

    $verb = [string]$gitArgs[0]
    if ($verb -eq "rev-parse" -and ($gitArgs -contains "--show-toplevel")) {
        return New-HermesCommandResult -Stdout $State.RepoRoot
    }

    if ($verb -eq "remote" -and $gitArgs.Count -ge 3 -and $gitArgs[1] -eq "get-url") {
        $wantPush = $gitArgs -contains "--push"
        $urls = @($State.FetchUrls)
        if ($wantPush -and $null -ne $State.PushUrls) {
            $urls = @($State.PushUrls)
        }
        return New-HermesCommandResult -Stdout ([string]::Join("`n", $urls))
    }

    if ($verb -eq "config") {
        $key = $gitArgs[$gitArgs.Count - 1]
        if ($key -eq "remote.origin.mirror" -and ($gitArgs -contains "--get")) {
            if ($null -eq $State.Mirror) {
                return New-HermesCommandResult -ExitCode 1
            }
            $mirrorText = "false"
            if ([bool]$State.Mirror) {
                $mirrorText = "true"
            }
            return New-HermesCommandResult -Stdout $mirrorText
        }
        throw "Unexpected git config command: $([string]::Join(' ', $gitArgs))"
    }

    if ($verb -eq "fetch") {
        $State.Fetched = $true
        return New-HermesCommandResult
    }

    if ($verb -eq "rev-parse" -and ($gitArgs -contains "refs/remotes/origin/main")) {
        if (-not [bool]$State.Fetched) {
            return New-HermesCommandResult -ExitCode 128 -Stderr "origin/main was read before fetch."
        }
        return New-HermesCommandResult -Stdout $State.OriginMain
    }

    if ($verb -eq "show-ref") {
        $ref = $gitArgs[$gitArgs.Count - 1]
        if ($null -ne $State.LocalTag -and $ref -eq ("refs/tags/" + $State.LocalTag.Name)) {
            return New-HermesCommandResult
        }
        return New-HermesCommandResult -ExitCode 1
    }

    if ($verb -eq "cat-file") {
        if ($null -eq $State.LocalTag) {
            return New-HermesCommandResult -ExitCode 128 -Stderr "missing local tag"
        }
        return New-HermesCommandResult -Stdout $State.LocalTag.Type
    }

    $isTagPeel = $false
    foreach ($gitArg in $gitArgs) {
        if ([string]$gitArg -like "refs/tags/*^{commit}") {
            $isTagPeel = $true
            break
        }
    }
    if ($verb -eq "rev-parse" -and $isTagPeel) {
        if ($null -eq $State.LocalTag) {
            return New-HermesCommandResult -ExitCode 1
        }
        return New-HermesCommandResult -Stdout $State.LocalTag.Sha
    }

    if ($verb -eq "ls-remote") {
        if ([int]$State.LsRemoteExit -ne 0) {
            return New-HermesCommandResult -ExitCode ([int]$State.LsRemoteExit) -Stderr "simulated ls-remote network failure"
        }
        $remote = $null
        if ($gitArgs.Count -ge 3) {
            $remote = [string]$gitArgs[$gitArgs.Count - 2]
        }
        $allowedRemotes = @($State.FetchUrls)
        if ($null -ne $State.PushUrls) {
            $allowedRemotes = @($State.PushUrls)
        }
        if (@($allowedRemotes) -notcontains $remote) {
            throw "ls-remote must use the verified publication URL, got '$remote'."
        }
        $wanted = $gitArgs[$gitArgs.Count - 1]
        if ($null -eq $State.RemoteTag) {
            return New-HermesCommandResult
        }
        $tagRef = "refs/tags/" + $State.RemoteTag.Name
        $peeledRef = $tagRef + "^{}"
        if ($wanted -eq $peeledRef) {
            return New-HermesCommandResult -Stdout ($State.RemoteTag.Sha + "`t" + $peeledRef)
        }
        if ($wanted -eq $tagRef) {
            $objectSha = $State.RemoteTag.Sha
            if ([bool]$State.RemoteTag.Annotated) {
                $objectSha = New-FakeTagObjectSha -CommitSha $State.RemoteTag.Sha
            }
            return New-HermesCommandResult -Stdout ($objectSha + "`t" + $tagRef)
        }
        return New-HermesCommandResult
    }

    if ($verb -eq "tag") {
        if ($gitArgs -contains "-f" -or $gitArgs -contains "--force") {
            $State.ForcedTag = $true
            return New-HermesCommandResult -ExitCode 1 -Stderr "force tag is forbidden in tests"
        }
        if ($gitArgs -contains "-d" -or $gitArgs -contains "--delete") {
            $State.DeletedTag = $true
            return New-HermesCommandResult -ExitCode 1 -Stderr "delete tag is forbidden in tests"
        }
        if (-not ($gitArgs -contains "-a")) {
            throw "New tags must be annotated (-a)."
        }
        $tagName = $gitArgs[2]
        $sha = $gitArgs[$gitArgs.Count - 1]
        $State.LocalTag = @{
            Name = $tagName
            Sha  = $sha
            Type = "tag"
        }
        return New-HermesCommandResult
    }

    if ($verb -eq "push") {
        if ($gitArgs -contains "--force" -or $gitArgs -contains "-f" -or $gitArgs -contains "--delete" -or $gitArgs -contains "--tags" -or $gitArgs -contains "--mirror" -or $gitArgs -contains "--all") {
            throw "Forbidden git push flag: $([string]::Join(' ', $gitArgs))"
        }
        if (-not ($gitArgs -contains "--no-follow-tags")) {
            throw "git push must pass --no-follow-tags. Args: $([string]::Join(' ', $gitArgs))"
        }
        $expectedPushUrls = @($State.FetchUrls)
        if ($null -ne $State.PushUrls) {
            $expectedPushUrls = @($State.PushUrls)
        }
        if ($expectedPushUrls.Count -ne 1) {
            throw "Fake push reached with multiple configured push URLs."
        }
        $expectedArgv = @("push", "--no-follow-tags", [string]$expectedPushUrls[0], "refs/tags/v0.5.0:refs/tags/v0.5.0")
        if ($gitArgs.Count -ne $expectedArgv.Count) {
            throw "Unexpected git push arguments: $([string]::Join(' ', $gitArgs))"
        }
        for ($i = 0; $i -lt $expectedArgv.Count; $i++) {
            if ([string]$gitArgs[$i] -ne [string]$expectedArgv[$i]) {
                throw "Unexpected git push arguments: $([string]::Join(' ', $gitArgs))"
            }
        }
        $refspec = [string]$gitArgs[$gitArgs.Count - 1]
        if ([bool]$State.FailPush) {
            return New-HermesCommandResult -ExitCode 1 -Stderr "simulated tag push failure"
        }
        if ($null -eq $State.LocalTag) {
            throw "Push requested but no local tag exists."
        }
        $State.RemoteTag = @{
            Name      = $State.LocalTag.Name
            Sha       = $State.LocalTag.Sha
            Annotated = $true
        }
        return New-HermesCommandResult
    }

    throw "Unexpected git command: $([string]::Join(' ', $gitArgs))"
}

function Invoke-FakeGhCommand {
    param($State, [string[]]$Arguments)

    $ghArgs = @($Arguments)
    if ($ghArgs.Count -eq 0) {
        throw "Fake gh received no arguments."
    }

    if ($ghArgs[0] -eq "auth" -and $ghArgs[1] -eq "status") {
        return New-HermesCommandResult -ExitCode ([int]$State.GhAuthExit) -Stderr $(if ([int]$State.GhAuthExit -ne 0) { "not logged in" } else { "" })
    }

    if ($ghArgs[0] -eq "run" -and $ghArgs[1] -eq "list") {
        $workflow = Get-RequestFlagValue -Arguments $ghArgs -Flag "--workflow"
        $commit = Get-RequestFlagValue -Arguments $ghArgs -Flag "--commit"
        if ($workflow -ne "ci.yml") {
            return New-HermesCommandResult -Stdout "[]"
        }
        $filtered = @()
        foreach ($run in @($State.CiRuns)) {
            if ([string]::IsNullOrWhiteSpace($commit) -or [string]$run.headSha -eq $commit) {
                $filtered += $run
            }
        }
        return New-HermesCommandResult -Stdout (New-HermesTestJson -Object $filtered)
    }

    if ($ghArgs[0] -eq "api") {
        $apiPath = $null
        foreach ($arg in $ghArgs) {
            if ($arg -like "repos/LTstripes/hermes-finance/releases/tags/*") {
                $apiPath = $arg
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($apiPath)) {
            throw "Unexpected gh api path: $([string]::Join(' ', $ghArgs))"
        }
        if ([string]$State.ReleaseApiFailure -eq "auth") {
            return New-HermesCommandResult -ExitCode 1 -Stderr "gh: HTTP 401 Unauthorized"
        }
        if ([string]$State.ReleaseApiFailure -eq "network") {
            return New-HermesCommandResult -ExitCode 1 -Stderr "dial tcp: simulated network failure"
        }
        if ([string]$State.ReleaseApiFailure -eq "500") {
            return New-HermesCommandResult -ExitCode 1 -Stderr "gh: Internal Server Error (HTTP 500)"
        }
        if ($null -eq $State.Release) {
            return New-HermesCommandResult -ExitCode 1 -Stderr "gh: Not Found (HTTP 404)"
        }
        $payload = @{
            tag_name   = $State.Release.tagName
            name       = $State.Release.name
            draft      = [bool]$State.Release.isDraft
            prerelease = [bool]$State.Release.isPrerelease
            html_url   = $State.Release.url
        }
        return New-HermesCommandResult -Stdout ($payload | ConvertTo-Json -Compress)
    }

    if ($ghArgs[0] -eq "release" -and $ghArgs[1] -eq "create") {
        if ([bool]$State.FailReleaseCreate) {
            return New-HermesCommandResult -ExitCode 1 -Stderr "simulated GitHub Release failure"
        }
        if ($ghArgs -contains "--target") {
            throw "gh release create must not use --target."
        }
        if ($ghArgs -contains "--draft" -or $ghArgs -contains "-d") {
            throw "gh release create must not use --draft."
        }
        if ($ghArgs -contains "--prerelease" -or $ghArgs -contains "-p") {
            throw "gh release create must not use --prerelease."
        }
        if (-not ($ghArgs -contains "--verify-tag")) {
            throw "gh release create must use --verify-tag."
        }
        $tag = [string]$ghArgs[2]
        $State.Release = @{
            tagName      = $tag
            name         = (Get-RequestFlagValue -Arguments $ghArgs -Flag "--title")
            isDraft      = $false
            isPrerelease = $false
            url          = "https://github.com/LTstripes/hermes-finance/releases/tag/$tag"
        }
        return New-HermesCommandResult -Stdout $State.Release.url
    }

    throw "Unexpected gh command: $([string]::Join(' ', $ghArgs))"
}

function New-DefaultResolver {
    param([switch]$MissingGh, [switch]$MissingGit)

    $denyGit = [bool]$MissingGit
    $denyGh = [bool]$MissingGh
    return {
        param([string]$Name)

        if ($Name -eq "git") {
            if ($denyGit) {
                return $null
            }
            return "git"
        }
        if ($Name -eq "gh") {
            if ($denyGh) {
                return $null
            }
            return "gh"
        }
        return $null
    }.GetNewClosure()
}

function Get-PublicationCalls {
    param($Calls)

    $found = New-Object System.Collections.ArrayList
    foreach ($call in @($Calls)) {
        if (Test-HermesIsPublicationCommand -Name $call.Name -Arguments @($call.Arguments)) {
            [void]$found.Add($call)
        }
    }
    foreach ($item in $found) {
        $item
    }
}

function Get-CallsByPrefix {
    param($Calls, [string]$Name, [string[]]$Prefix)

    $found = New-Object System.Collections.ArrayList
    foreach ($call in @($Calls)) {
        if ($call.Name -ne $Name) {
            continue
        }
        $argsToMatch = @($call.Arguments)
        if ($Name -eq "git") {
            $argsToMatch = @(Get-HermesGitArgsWithoutC -Arguments $argsToMatch)
        }
        $ok = $true
        for ($i = 0; $i -lt $Prefix.Count; $i++) {
            if ($i -ge $argsToMatch.Count -or [string]$argsToMatch[$i] -ne [string]$Prefix[$i]) {
                $ok = $false
                break
            }
        }
        if ($ok) {
            [void]$found.Add($call)
        }
    }
    foreach ($item in $found) {
        $item
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)

    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)

    if ($Expected -ne $Actual) {
        throw "Expected $Label to be [$Expected], got [$Actual]."
    }
}

function Assert-NoPublication {
    param($Calls, [string]$Label)

    $mutations = @(Get-PublicationCalls -Calls $Calls)
    if ($mutations.Count -ne 0) {
        $shown = ($mutations | ForEach-Object { $_.Name + " " + [string]::Join(" ", $_.Arguments) }) -join "; "
        throw "$Label caused publication commands: $shown"
    }
}

function Invoke-ExpectFailure {
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

    if (-not $threw) {
        throw "Expected a failure matching /$Pattern/."
    }
    if ($message -notmatch $Pattern) {
        throw "Expected error /$Pattern/, got: $message"
    }

    return $message
}

function Invoke-GuardedRelease {
    param(
        [Parameter(Mandatory = $true)]
        $Workspace,
        [Parameter(Mandatory = $true)]
        $World,
        [string]$Version = "0.5.0",
        [string]$ExpectedMainSha = $script:ExpectedSha,
        $ReleaseNotes,
        [scriptblock]$CommandResolver = $null
    )

    if ([string]::IsNullOrWhiteSpace([string]$ReleaseNotes)) {
        $ReleaseNotes = $Workspace.NotesPath
    }
    if ($null -eq $CommandResolver) {
        $CommandResolver = New-DefaultResolver
    }

    return Invoke-HermesRelease `
        -Version $Version `
        -ExpectedMainSha $ExpectedMainSha `
        -ReleaseNotes $ReleaseNotes `
        -RepoRoot $Workspace.RepoRoot `
        -CommandRunner $World.Runner `
        -CommandResolver $CommandResolver
}

function Invoke-HermesCase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Body
    )

    try {
        & $Body
        $script:Passed += 1
        Write-Host "PASS $Name" -ForegroundColor Green
    }
    catch {
        $script:Failed += 1
        Write-Host "FAIL $Name" -ForegroundColor Red
        Write-Host "     $($_.Exception.Message)" -ForegroundColor Red
    }
}

Invoke-HermesCase "canonical tag name accepts X.Y.Z and vX.Y.Z" {
    Assert-Equal -Expected "v0.5.0" -Actual (Get-HermesCanonicalTagName -Version "0.5.0") -Label "0.5.0"
    Assert-Equal -Expected "v0.5.0" -Actual (Get-HermesCanonicalTagName -Version "v0.5.0") -Label "v0.5.0"
    Assert-Equal -Expected "v1.0.0" -Actual (Get-HermesCanonicalTagName -Version " 1.0.0 ") -Label "trimmed"
}

Invoke-HermesCase "malformed versions are rejected" {
    foreach ($version in @("", "0.5", "v0.5", "0.5.0-rc1", "v0.5.0.1", "latest", "v", "00.5.0")) {
        Invoke-ExpectFailure -Pattern "Malformed version|Version is required" -Script {
            Get-HermesCanonicalTagName -Version $version
        } | Out-Null
    }
}

Invoke-HermesCase "ExpectedMainSha must be a full 40-character SHA" {
    Invoke-ExpectFailure -Pattern "40-character" -Script { Get-HermesNormalizedCommitSha -Sha "abc1234" } | Out-Null
    Invoke-ExpectFailure -Pattern "40-character" -Script { Get-HermesNormalizedCommitSha -Sha "main" } | Out-Null
    Invoke-ExpectFailure -Pattern "40-character" -Script { Get-HermesNormalizedCommitSha -Sha "HEAD" } | Out-Null
    Assert-Equal `
        -Expected $script:ExpectedSha `
        -Actual (Get-HermesNormalizedCommitSha -Sha $script:ExpectedSha.ToUpperInvariant()) `
        -Label "normalized sha"
}

Invoke-HermesCase "origin URL must resolve to LTstripes/hermes-finance" {
    Test-HermesExpectedGitHubRemote -Url "https://github.com/LTstripes/hermes-finance.git"
    $at = [string][char]64
    Test-HermesExpectedGitHubRemote -Url ("git" + $at + "github.com:LTstripes/hermes-finance.git")
    Test-HermesExpectedGitHubRemote -Url ("ssh://git" + $at + "github.com/LTstripes/hermes-finance.git")
    Invoke-ExpectFailure -Pattern "does not point" -Script {
        Test-HermesExpectedGitHubRemote -Url "https://github.com/other/hermes-finance.git"
    } | Out-Null
}

Invoke-HermesCase "malformed version performs zero commands" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    Invoke-ExpectFailure -Pattern "Malformed version" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world -Version "0.5.0-rc1"
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "command count"
}

Invoke-HermesCase "invalid SHA performs zero commands" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    Invoke-ExpectFailure -Pattern "40-character" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world -ExpectedMainSha "deadbeef"
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "command count"
}

Invoke-HermesCase "missing release notes perform zero commands" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    Invoke-ExpectFailure -Pattern "not found" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world -ReleaseNotes (Join-Path $workspace.RepoRoot "missing.md")
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "command count"
}

Invoke-HermesCase "empty release notes perform zero commands" {
    $workspace = New-HermesTestWorkspace
    $emptyNotes = Join-Path $workspace.RepoRoot "empty.md"
    [IO.File]::WriteAllText($emptyNotes, "", (New-Object System.Text.UTF8Encoding $false))
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    Invoke-ExpectFailure -Pattern "empty" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world -ReleaseNotes $emptyNotes
    } | Out-Null
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "command count"
}

Invoke-HermesCase "missing gh fails closed with no fallback and no mutation" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    $message = Invoke-ExpectFailure -Pattern "Missing dependency 'gh'|will not fall back" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world -CommandResolver (New-DefaultResolver -MissingGh)
    }
    Assert-True -Condition ($message -match "\.env") -Message "Missing-gh error should mention that .env is not used."
    Assert-Equal -Expected 0 -Actual @($world.State.Calls).Count -Label "command count"
    Assert-NoPublication -Calls $world.State.Calls -Label "missing gh"
}

Invoke-HermesCase "unauthenticated gh fails closed with no mutation" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -GhAuthExit 1
    $message = Invoke-ExpectFailure -Pattern "not authenticated|will not read tokens" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    }
    Assert-True -Condition ($message -match "\.env") -Message "Unauthenticated error should mention that .env is not used."
    Assert-NoPublication -Calls $world.State.Calls -Label "unauthenticated gh"
    Assert-Equal -Expected 0 -Actual @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("fetch")).Count -Label "fetch before auth failure is optional; publication is forbidden"
}

Invoke-HermesCase "SHA mismatch after fetch performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -OriginMain $script:OtherSha
    Invoke-ExpectFailure -Pattern "origin/main is $($script:OtherSha)" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-True -Condition ([bool]$world.State.Fetched) -Message "Remote must be fetched before the SHA decision."
    Assert-NoPublication -Calls $world.State.Calls -Label "SHA mismatch"
}

Invoke-HermesCase "CI not success performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $failed = New-SuccessfulCiRun
    $failed.conclusion = "failure"
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -CiRuns @($failed)
    Invoke-ExpectFailure -Pattern "not completed/success" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "failed CI"
}

Invoke-HermesCase "in-progress CI performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $running = New-SuccessfulCiRun
    $running.status = "in_progress"
    $running.conclusion = ""
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -CiRuns @($running)
    Invoke-ExpectFailure -Pattern "not completed/success" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "in-progress CI"
}

Invoke-HermesCase "missing exact-main CI performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -CiRuns @()
    Invoke-ExpectFailure -Pattern "No exact-main GitHub Actions CI" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "missing CI"
}

Invoke-HermesCase "pull_request CI is not accepted as exact-main CI" {
    $workspace = New-HermesTestWorkspace
    $pr = New-SuccessfulCiRun
    $pr.event = "pull_request"
    $pr.headBranch = "m04-01-release-helper"
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -CiRuns @($pr)
    Invoke-ExpectFailure -Pattern "No exact-main GitHub Actions CI" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "PR CI only"
}

Invoke-HermesCase "existing remote tag on the wrong SHA fails closed" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -RemoteTag @{
        Name      = $script:TagName
        Sha       = $script:OtherSha
        Annotated = $true
    }
    Invoke-ExpectFailure -Pattern "already points to $($script:OtherSha)|Refusing to force-update" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "wrong remote tag"
    Assert-True -Condition (-not [bool]$world.State.ForcedTag) -Message "Must not force-update a tag."
    Assert-True -Condition (-not [bool]$world.State.DeletedTag) -Message "Must not delete a tag."
}

Invoke-HermesCase "existing local tag on the wrong SHA fails closed" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -LocalTag @{
        Name = $script:TagName
        Sha  = $script:OtherSha
        Type = "tag"
    }
    Invoke-ExpectFailure -Pattern "Local tag $script:TagName already points" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "wrong local tag"
}

Invoke-HermesCase "existing lightweight tag fails closed even on the expected SHA" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -RemoteTag @{
        Name      = $script:TagName
        Sha       = $script:ExpectedSha
        Annotated = $false
    }
    Invoke-ExpectFailure -Pattern "not an annotated tag" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "lightweight tag"
}

Invoke-HermesCase "successful publish uses fetch-then-tag-then-tag-push-then-release" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    $result = Invoke-GuardedRelease -Workspace $workspace -World $world

    Assert-Equal -Expected "0.5.0" -Actual $result.Version -Label "version"
    Assert-Equal -Expected $script:TagName -Actual $result.Tag -Label "tag"
    Assert-Equal -Expected $script:ExpectedSha -Actual $result.Sha -Label "sha"
    Assert-True -Condition ([bool]$result.TagCreated) -Message "Expected a new annotated tag."
    Assert-True -Condition ([bool]$result.TagPushed) -Message "Expected a tag push."
    Assert-True -Condition ([bool]$result.ReleaseCreated) -Message "Expected GitHub Release creation."

    $names = @()
    foreach ($call in @($world.State.Calls)) {
        $argsToMatch = @($call.Arguments)
        if ($call.Name -eq "git") {
            $argsToMatch = @(Get-HermesGitArgsWithoutC -Arguments $argsToMatch)
        }
        if ($call.Name -eq "git" -and $argsToMatch.Count -gt 0) {
            $names += "git:" + $argsToMatch[0]
        }
        elseif ($call.Name -eq "gh" -and $argsToMatch.Count -ge 2) {
            $names += "gh:" + $argsToMatch[0] + ":" + $argsToMatch[1]
        }
    }

    $fetchAt = [array]::IndexOf($names, "git:fetch")
    $tagAt = [array]::IndexOf($names, "git:tag")
    $pushAt = [array]::IndexOf($names, "git:push")
    $releaseAt = [array]::IndexOf($names, "gh:release:create")
    $ciAt = [array]::IndexOf($names, "gh:run:list")
    Assert-True -Condition ($fetchAt -ge 0) -Message "fetch must run."
    Assert-True -Condition ($ciAt -gt $fetchAt) -Message "CI check must run after fetch."
    Assert-True -Condition ($tagAt -gt $ciAt) -Message "tag must run after CI."
    Assert-True -Condition ($pushAt -gt $tagAt) -Message "push must run after tag."
    Assert-True -Condition ($releaseAt -gt $pushAt) -Message "release create must run after tag push."

    $pushes = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("push"))
    Assert-Equal -Expected 1 -Actual $pushes.Count -Label "git push count"
    $pushArgs = @(Get-HermesGitArgsWithoutC -Arguments $pushes[0].Arguments)
    Assert-Equal -Expected 4 -Actual $pushArgs.Count -Label "git push argc"
    Assert-Equal -Expected "push" -Actual $pushArgs[0] -Label "push verb"
    Assert-Equal -Expected "--no-follow-tags" -Actual $pushArgs[1] -Label "push follow-tags override"
    Assert-Equal -Expected $script:CanonicalUrl -Actual $pushArgs[2] -Label "push destination URL"
    Assert-Equal -Expected "refs/tags/v0.5.0:refs/tags/v0.5.0" -Actual $pushArgs[3] -Label "push refspec"
    Assert-True -Condition ($pushArgs -notcontains "origin") -Message "Publication push must use the verified URL, not the remote name."
    Assert-True -Condition ($pushArgs -notcontains "--mirror") -Message "Push must not use --mirror."
    Assert-True -Condition ($pushArgs -notcontains "--tags") -Message "Push must not use --tags."

    $runLists = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("run", "list"))
    Assert-Equal -Expected 1 -Actual $runLists.Count -Label "gh run list count"
    Assert-Equal -Expected "ci.yml" -Actual (Get-RequestFlagValue -Arguments $runLists[0].Arguments -Flag "--workflow") -Label "CI workflow"
    Assert-Equal -Expected $script:ExpectedSha -Actual (Get-RequestFlagValue -Arguments $runLists[0].Arguments -Flag "--commit") -Label "CI commit"

    $urlInspect = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("remote", "get-url", "--all"))
    $pushInspect = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("remote", "get-url", "--push", "--all"))
    $mirrorInspect = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("config", "--bool", "--get", "remote.origin.mirror"))
    Assert-True -Condition ($urlInspect.Count -ge 1) -Message "Must inspect all origin fetch URLs."
    Assert-True -Condition ($pushInspect.Count -ge 1) -Message "Must inspect all origin push URLs."
    Assert-True -Condition ($mirrorInspect.Count -ge 1) -Message "Must read remote.origin.mirror before publishing."

    $creates = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("release", "create"))
    Assert-Equal -Expected 1 -Actual $creates.Count -Label "release create count"
    Assert-True -Condition (@($creates[0].Arguments) -contains "--verify-tag") -Message "release create must use --verify-tag."
    Assert-True -Condition (-not (@($creates[0].Arguments) -contains "--target")) -Message "release create must not use --target."
    Assert-True -Condition (-not (@($creates[0].Arguments) -contains "--draft")) -Message "release create must not be a draft."
    Assert-True -Condition (-not (@($creates[0].Arguments) -contains "--prerelease")) -Message "release create must not be a prerelease."

    $apiCalls = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("api"))
    Assert-True -Condition ($apiCalls.Count -ge 2) -Message "Release probe must run before create and again for final read-back."
    $lsRemote = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("ls-remote"))
    Assert-True -Condition ($lsRemote.Count -ge 4) -Message "Remote tag must be read before publish and again after push/final read-back."
    $createNameAt = [array]::IndexOf($names, "gh:release:create")
    $apiAfterCreate = 0
    for ($i = $createNameAt + 1; $i -lt $names.Count; $i++) {
        if ($names[$i] -eq "gh:api:--method") {
            $apiAfterCreate += 1
        }
    }
    Assert-True -Condition ($apiAfterCreate -ge 1) -Message "Final read-back must probe the GitHub Release after create."
}

Invoke-HermesCase "successful publish never pushes a branch or unrelated ref" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    Invoke-GuardedRelease -Workspace $workspace -World $world | Out-Null

    foreach ($call in @($world.State.Calls)) {
        Assert-True -Condition (@("git", "gh") -contains $call.Name) -Message "Unexpected tool $($call.Name)."
        if ($call.Name -ne "git") {
            continue
        }
        $gitArgs = @(Get-HermesGitArgsWithoutC -Arguments $call.Arguments)
        if ($gitArgs.Count -eq 0) {
            continue
        }
        Assert-True -Condition (@("commit", "checkout", "switch", "merge", "rebase", "branch") -notcontains $gitArgs[0]) -Message "Forbidden git verb $($gitArgs[0])."
        if ($gitArgs[0] -eq "push") {
            $refspec = [string]$gitArgs[$gitArgs.Count - 1]
            Assert-True -Condition ($gitArgs -contains "--no-follow-tags") -Message "Push must disable followTags."
            Assert-True -Condition ($refspec -match "^refs/tags/") -Message "Push must target a tag ref, got $refspec."
            Assert-True -Condition ($refspec -notmatch "refs/heads/") -Message "Push must not include a branch ref."
            Assert-True -Condition ($gitArgs -notcontains "main") -Message "Push must not mention main."
            Assert-True -Condition ($gitArgs -notcontains "HEAD") -Message "Push must not mention HEAD."
            Assert-True -Condition ($gitArgs -notcontains "--tags") -Message "Push must not use --tags."
            Assert-True -Condition ($gitArgs -notcontains "--mirror") -Message "Push must not use --mirror."
            Assert-True -Condition ($gitArgs -notcontains "origin") -Message "Push must not blindly use the remote name."
        }
    }
}

Invoke-HermesCase "tag push success plus release failure is partial and does not delete the tag" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -FailReleaseCreate
    $message = Invoke-ExpectFailure -Pattern "PARTIAL: tag v0.5.0 is on origin" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    }
    Assert-True -Condition ($message -match "Re-run") -Message "Partial failure must describe the safe rerun path."
    Assert-True -Condition ($null -ne $world.State.RemoteTag) -Message "Remote tag must remain after release failure."
    Assert-Equal -Expected $script:ExpectedSha -Actual $world.State.RemoteTag.Sha -Label "remote tag sha"
    Assert-True -Condition (-not [bool]$world.State.DeletedTag) -Message "Partial failure must not delete the tag."
    Assert-True -Condition (-not [bool]$world.State.ForcedTag) -Message "Partial failure must not force-update the tag."
    Assert-True -Condition ($null -eq $world.State.Release) -Message "Release must not exist after the simulated failure."
}

Invoke-HermesCase "safe rerun after partial publication only creates the Release" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld `
        -RepoRoot $workspace.RepoRoot `
        -LocalTag @{ Name = $script:TagName; Sha = $script:ExpectedSha; Type = "tag" } `
        -RemoteTag @{ Name = $script:TagName; Sha = $script:ExpectedSha; Annotated = $true }

    $result = Invoke-GuardedRelease -Workspace $workspace -World $world
    Assert-True -Condition ([bool]$result.ReusedExistingTag) -Message "Rerun must reuse the existing tag."
    Assert-True -Condition (-not [bool]$result.TagCreated) -Message "Rerun must not create a new tag."
    Assert-True -Condition (-not [bool]$result.TagPushed) -Message "Rerun must not push the tag again."
    Assert-True -Condition ([bool]$result.ReleaseCreated) -Message "Rerun must create the missing Release."

    $tags = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("tag"))
    $pushes = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("push"))
    $creates = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("release", "create"))
    Assert-Equal -Expected 0 -Actual $tags.Count -Label "rerun git tag count"
    Assert-Equal -Expected 0 -Actual $pushes.Count -Label "rerun git push count"
    Assert-Equal -Expected 1 -Actual $creates.Count -Label "rerun release create count"
}

Invoke-HermesCase "already published release is idempotent and does not mutate" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld `
        -RepoRoot $workspace.RepoRoot `
        -RemoteTag @{ Name = $script:TagName; Sha = $script:ExpectedSha; Annotated = $true } `
        -Release @{
            tagName      = $script:TagName
            name         = "Hermes Finance 0.5.0"
            isDraft      = $false
            isPrerelease = $false
            url          = "https://github.com/LTstripes/hermes-finance/releases/tag/v0.5.0"
        }

    $result = Invoke-GuardedRelease -Workspace $workspace -World $world
    Assert-True -Condition (-not [bool]$result.TagCreated) -Message "Idempotent run must not create a tag."
    Assert-True -Condition (-not [bool]$result.TagPushed) -Message "Idempotent run must not push a tag."
    Assert-True -Condition (-not [bool]$result.ReleaseCreated) -Message "Idempotent run must not recreate the Release."
    Assert-NoPublication -Calls $world.State.Calls -Label "already published"
}

Invoke-HermesCase "notes path with spaces and Cyrillic is passed as --notes-file" {
    $workspace = New-HermesTestWorkspace -CyrillicNotes
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot
    Invoke-GuardedRelease -Workspace $workspace -World $world -ReleaseNotes $workspace.NotesPath | Out-Null

    $creates = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("release", "create"))
    Assert-Equal -Expected 1 -Actual $creates.Count -Label "release create count"
    $notesArg = Get-RequestFlagValue -Arguments $creates[0].Arguments -Flag "--notes-file"
    Assert-Equal -Expected $workspace.NotesPath -Actual $notesArg -Label "notes-file"
    Assert-True -Condition ($notesArg -match " ") -Message "Notes path should contain a space."
    Assert-True -Condition ($notesArg -like ("*" + (New-CyrillicToken -Which "notes") + "*")) -Message "Notes path should contain Cyrillic."
    $cPath = Get-RequestFlagValue -Arguments $world.State.Calls[0].Arguments -Flag "-C"
    Assert-True -Condition (([string]$cPath).Length -gt 0) -Message "git -C must receive the repo root."
}

Invoke-HermesCase "wrong origin remote fails before publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -OriginUrl "https://github.com/example/not-hermes.git"
    Invoke-ExpectFailure -Pattern "does not point to LTstripes/hermes-finance" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "wrong origin"
}

Invoke-HermesCase "canonical fetch URL plus wrong pushurl performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld `
        -RepoRoot $workspace.RepoRoot `
        -FetchUrls @($script:CanonicalUrl) `
        -PushUrls @("https://github.com/example/not-hermes.git")
    Invoke-ExpectFailure -Pattern "does not point to LTstripes/hermes-finance" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "wrong pushurl"
}

Invoke-HermesCase "canonical fetch URL plus multiple pushurls performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld `
        -RepoRoot $workspace.RepoRoot `
        -FetchUrls @($script:CanonicalUrl) `
        -PushUrls @($script:CanonicalUrl, "https://www.github.com/LTstripes/hermes-finance.git")
    Invoke-ExpectFailure -Pattern "multiple effective push destinations" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "multiple pushurls"
}

Invoke-HermesCase "multiple ordinary URLs with no pushurl fail closed" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld `
        -RepoRoot $workspace.RepoRoot `
        -FetchUrls @($script:CanonicalUrl, "https://www.github.com/LTstripes/hermes-finance.git")
    Invoke-ExpectFailure -Pattern "multiple effective push destinations" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "multiple ordinary URLs"
}

Invoke-HermesCase "one canonical effective push destination is allowed" {
    $workspace = New-HermesTestWorkspace
    $pushUrl = "https://www.github.com/LTstripes/hermes-finance.git"
    $world = New-HermesFakeWorld `
        -RepoRoot $workspace.RepoRoot `
        -FetchUrls @($script:CanonicalUrl) `
        -PushUrls @($pushUrl)
    $result = Invoke-GuardedRelease -Workspace $workspace -World $world
    Assert-True -Condition ([bool]$result.ReleaseCreated) -Message "Single canonical push destination must be allowed."
    $pushes = @(Get-CallsByPrefix -Calls $world.State.Calls -Name "git" -Prefix @("push"))
    Assert-Equal -Expected 1 -Actual $pushes.Count -Label "push count"
    $pushArgs = @(Get-HermesGitArgsWithoutC -Arguments $pushes[0].Arguments)
    Assert-Equal -Expected $pushUrl -Actual $pushArgs[2] -Label "verified push URL"
}

Invoke-HermesCase "remote.origin.mirror true performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -Mirror $true
    Invoke-ExpectFailure -Pattern "remote\.origin\.mirror is true" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "mirror mode"
}

Invoke-HermesCase "ls-remote network failure performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -LsRemoteExit 128
    Invoke-ExpectFailure -Pattern "Command failed \(exit 128\)|simulated ls-remote" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "ls-remote failure"
}

Invoke-HermesCase "release probe auth failure performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -ReleaseApiFailure "auth"
    Invoke-ExpectFailure -Pattern "Not treating the failure as a missing release|HTTP 401" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "release auth failure"
    Assert-Equal -Expected 0 -Actual @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("release", "create")).Count -Label "release create count"
}

Invoke-HermesCase "release probe network failure performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -ReleaseApiFailure "network"
    Invoke-ExpectFailure -Pattern "Not treating the failure as a missing release|simulated network failure" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "release network failure"
    Assert-Equal -Expected 0 -Actual @(Get-CallsByPrefix -Calls $world.State.Calls -Name "gh" -Prefix @("release", "create")).Count -Label "release create count"
}

Invoke-HermesCase "PR success plus failed exact-main CI performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $pr = New-SuccessfulCiRun
    $pr.event = "pull_request"
    $failedMain = New-SuccessfulCiRun
    $failedMain.conclusion = "failure"
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -CiRuns @($pr, $failedMain)
    Invoke-ExpectFailure -Pattern "not completed/success" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "PR success with failed main CI"
}

Invoke-HermesCase "feature-branch success plus failed main CI performs zero publication" {
    $workspace = New-HermesTestWorkspace
    $feature = New-SuccessfulCiRun
    $feature.headBranch = "m04-01-release-helper"
    $failedMain = New-SuccessfulCiRun
    $failedMain.conclusion = "failure"
    $world = New-HermesFakeWorld -RepoRoot $workspace.RepoRoot -CiRuns @($feature, $failedMain)
    Invoke-ExpectFailure -Pattern "not completed/success" -Script {
        Invoke-GuardedRelease -Workspace $workspace -World $world
    } | Out-Null
    Assert-NoPublication -Calls $world.State.Calls -Label "feature-branch success with failed main CI"
}

try {
    Write-Host ""
    Write-Host "Passed: $script:Passed  Failed: $script:Failed"
    if ($script:Failed -gt 0) {
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
