# Guarded Windows release helper library for Hermes Finance.
# Public CLI: scripts/release.ps1. Tests inject a fake command runner.

Set-StrictMode -Version 2.0

$script:HermesReleaseOwner = "LTstripes"
$script:HermesReleaseRepo = "hermes-finance"
$script:HermesReleaseSlug = "LTstripes/hermes-finance"
$script:HermesReleaseWorkflow = "ci.yml"

function Write-HermesReleaseStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host "==> $Message" -ForegroundColor Cyan
}

function New-HermesCommandResult {
    param(
        [int]$ExitCode = 0,
        [string]$Stdout = "",
        [string]$Stderr = ""
    )

    return [pscustomobject]@{
        ExitCode = [int]$ExitCode
        Stdout   = [string]$Stdout
        Stderr   = [string]$Stderr
    }
}

function Get-HermesGitArgsWithoutC {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Arguments
    )

    $output = New-Object System.Collections.Generic.List[string]
    $i = 0
    $items = @($Arguments)
    while ($i -lt $items.Count) {
        if ($items[$i] -eq "-C" -and ($i + 1) -lt $items.Count) {
            $i += 2
            continue
        }
        [void]$output.Add([string]$items[$i])
        $i += 1
    }
    foreach ($item in $output) {
        $item
    }
}

function Test-HermesIsPublicationCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Arguments
    )

    $normalized = @($Arguments)
    if ($Name -eq "git") {
        $normalized = @(Get-HermesGitArgsWithoutC -Arguments $normalized)
        if ($normalized.Count -eq 0) {
            return $false
        }
        $verb = [string]$normalized[0]
        return @(
            "tag",
            "push",
            "commit",
            "checkout",
            "switch",
            "merge",
            "rebase",
            "reset",
            "branch",
            "cherry-pick",
            "stash"
        ) -contains $verb
    }

    if ($Name -eq "gh" -and $normalized.Count -ge 2 -and [string]$normalized[0] -eq "release") {
        return @("create", "delete", "edit", "upload") -contains [string]$normalized[1]
    }

    return $false
}

function Get-HermesCanonicalTagName {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Version
    )

    if ([string]::IsNullOrWhiteSpace($Version)) {
        throw "Version is required. Expected X.Y.Z or vX.Y.Z."
    }

    $trimmed = $Version.Trim()
    if ($trimmed -notmatch "^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") {
        throw "Malformed version '$Version'. Expected X.Y.Z or vX.Y.Z with no pre-release suffix."
    }

    $major = $Matches[1]
    $minor = $Matches[2]
    $patch = $Matches[3]
    return "v$major.$minor.$patch"
}

function Get-HermesNormalizedCommitSha {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Sha,
        [string]$Label = "ExpectedMainSha"
    )

    $trimmed = $Sha.Trim()
    if ($trimmed -notmatch "^[0-9a-fA-F]{40}$") {
        throw "$Label must be the full 40-character commit SHA, not a short hash, branch, or tag name."
    }

    return $trimmed.ToLowerInvariant()
}

function Test-HermesExpectedGitHubRemote {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Url
    )

    if ([string]::IsNullOrWhiteSpace($Url)) {
        throw "origin remote URL is empty; expected LTstripes/hermes-finance."
    }

    $normalized = $Url.Trim() -replace "\\", "/"
    $normalized = $normalized.TrimEnd("/")
    $normalized = $normalized -replace "\.git$", ""
    if ($normalized -notmatch "(?i)^(https://(www\.)?github\.com/|git@github\.com:|ssh://git@github\.com/)LTstripes/hermes-finance$") {
        throw "origin does not point to LTstripes/hermes-finance. Found: $Url"
    }
}

function Resolve-HermesReleaseNotesPath {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ReleaseNotes
    )

    if ([string]::IsNullOrWhiteSpace($ReleaseNotes)) {
        throw "ReleaseNotes is required. Pass a Markdown file; the helper will not invent notes."
    }

    $candidate = $ReleaseNotes
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path (Get-Location).Path $candidate
    }
    $fullPath = [IO.Path]::GetFullPath($candidate)
    if (-not (Test-Path -LiteralPath $fullPath)) {
        throw "Release notes file not found: $fullPath"
    }

    $item = Get-Item -LiteralPath $fullPath
    if ($item.PSIsContainer) {
        throw "ReleaseNotes must be a file, not a directory: $fullPath"
    }
    if ($item.Length -le 0) {
        throw "Release notes file is empty: $fullPath"
    }

    return $fullPath
}

function Resolve-HermesToolPath {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$CommandResolver,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    $resolved = & $CommandResolver $Name
    if ([string]::IsNullOrWhiteSpace([string]$resolved)) {
        throw $InstallHint
    }

    return [string]$resolved
}

function Convert-HermesJsonArray {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Stdout,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Stdout)) {
        throw "$Label returned empty JSON."
    }

    $parsed = $Stdout | ConvertFrom-Json
    if ($null -eq $parsed) {
        return @()
    }

    return @($parsed)
}

function Get-HermesLsRemoteSha {
    param(
        [AllowEmptyString()]
        [string]$Stdout
    )

    if ([string]::IsNullOrWhiteSpace($Stdout)) {
        return $null
    }

    $line = @(
        $Stdout -split "\r?\n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -First 1
    )
    if ($line.Count -eq 0) {
        return $null
    }

    $sha = (([string]$line[0]) -split "\s+")[0]
    if ($sha -notmatch "^[0-9a-fA-F]{40}$") {
        return $null
    }

    return $sha.ToLowerInvariant()
}

function New-HermesDefaultCommandResolver {
    return {
        param([string]$Name)

        $command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            return $null
        }

        return [string]$command.Source
    }
}

function Invoke-HermesNativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FileName,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @()
    )

    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $FileName @ArgumentList 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }

    if ($null -eq $code) {
        $code = 0
    }

    $stdoutParts = New-Object System.Collections.Generic.List[string]
    $stderrParts = New-Object System.Collections.Generic.List[string]
    foreach ($item in @($output)) {
        if ($item -is [System.Management.Automation.ErrorRecord]) {
            [void]$stderrParts.Add($item.ToString())
        }
        else {
            [void]$stdoutParts.Add([string]$item)
        }
    }

    return New-HermesCommandResult `
        -ExitCode $code `
        -Stdout ([string]::Join("`n", $stdoutParts.ToArray())) `
        -Stderr ([string]::Join("`n", $stderrParts.ToArray()))
}

function New-HermesDefaultCommandRunner {
    return {
        param($Request)

        return Invoke-HermesNativeCommand -FileName $Request.FileName -ArgumentList @($Request.Arguments)
    }
}

function Invoke-HermesTool {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @(),
        [switch]$AllowFailure
    )

    $fileName = $Name
    if ($Name -eq "git") {
        $fileName = $Context.GitPath
    }
    elseif ($Name -eq "gh") {
        $fileName = $Context.GhPath
    }

    $request = [pscustomobject]@{
        Name      = $Name
        FileName  = $fileName
        Arguments = @($ArgumentList)
    }

    $result = & $Context.CommandRunner $request
    if ($null -eq $result) {
        throw "Internal error: command runner returned nothing for $Name."
    }
    foreach ($propertyName in @("ExitCode", "Stdout", "Stderr")) {
        if ($null -eq $result.PSObject.Properties[$propertyName]) {
            throw "Internal error: command runner result missing '$propertyName'."
        }
    }

    if (-not $AllowFailure -and [int]$result.ExitCode -ne 0) {
        $detail = [string]$result.Stderr
        if ([string]::IsNullOrWhiteSpace($detail)) {
            $detail = [string]$result.Stdout
        }
        $display = "$Name $([string]::Join(' ', @($ArgumentList)))"
        throw "Command failed (exit $($result.ExitCode)): $display`n$detail"
    }

    return $result
}

function Get-HermesLocalTagInfo {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    $show = Invoke-HermesTool `
        -Context $Context `
        -Name "git" `
        -ArgumentList @("-C", $Context.RepoRoot, "show-ref", "--verify", "--quiet", "refs/tags/$Tag") `
        -AllowFailure
    if ([int]$show.ExitCode -ne 0) {
        return [pscustomobject]@{
            Exists    = $false
            Annotated = $false
            Sha       = $null
        }
    }

    $typeResult = Invoke-HermesTool `
        -Context $Context `
        -Name "git" `
        -ArgumentList @("-C", $Context.RepoRoot, "cat-file", "-t", "refs/tags/$Tag")
    $peel = Invoke-HermesTool `
        -Context $Context `
        -Name "git" `
        -ArgumentList @("-C", $Context.RepoRoot, "rev-parse", "--verify", "--quiet", "refs/tags/$Tag^{commit}")
    $sha = Get-HermesNormalizedCommitSha -Sha $peel.Stdout.Trim() -Label "Local tag $Tag"

    return [pscustomobject]@{
        Exists    = $true
        Annotated = ([string]$typeResult.Stdout.Trim() -eq "tag")
        Sha       = $sha
    }
}

function Get-HermesRemoteTagInfo {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    $plain = Invoke-HermesTool `
        -Context $Context `
        -Name "git" `
        -ArgumentList @("-C", $Context.RepoRoot, "ls-remote", "--tags", "origin", "refs/tags/$Tag") `
        -AllowFailure
    $peeled = Invoke-HermesTool `
        -Context $Context `
        -Name "git" `
        -ArgumentList @("-C", $Context.RepoRoot, "ls-remote", "--tags", "origin", "refs/tags/$Tag^{}") `
        -AllowFailure

    $tagObjectSha = Get-HermesLsRemoteSha -Stdout $plain.Stdout
    $commitSha = Get-HermesLsRemoteSha -Stdout $peeled.Stdout
    if ($null -eq $tagObjectSha -and $null -eq $commitSha) {
        return [pscustomobject]@{
            Exists    = $false
            Annotated = $false
            Sha       = $null
        }
    }

    if ($null -eq $commitSha) {
        return [pscustomobject]@{
            Exists    = $true
            Annotated = $false
            Sha       = $tagObjectSha
        }
    }

    $objectSha = $tagObjectSha
    if ($null -eq $objectSha) {
        $objectSha = $commitSha
    }

    return [pscustomobject]@{
        Exists    = $true
        Annotated = ($objectSha -ne $commitSha)
        Sha       = $commitSha
    }
}

function Resolve-HermesTagPlan {
    param(
        [Parameter(Mandatory = $true)]
        $Local,
        [Parameter(Mandatory = $true)]
        $Remote,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha,
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    if ($Remote.Exists) {
        if (-not [bool]$Remote.Annotated) {
            throw "Remote tag $Tag exists but is not an annotated tag. Refusing to move or recreate it."
        }
        if ([string]$Remote.Sha -ne $ExpectedSha) {
            throw "Remote tag $Tag already points to $($Remote.Sha), not $ExpectedSha. Refusing to force-update the tag."
        }
    }

    if ($Local.Exists) {
        if (-not [bool]$Local.Annotated) {
            throw "Local tag $Tag exists but is not an annotated tag. Refusing to move or recreate it."
        }
        if ([string]$Local.Sha -ne $ExpectedSha) {
            throw "Local tag $Tag already points to $($Local.Sha), not $ExpectedSha. Refusing to move or recreate it."
        }
    }

    if ($Remote.Exists) {
        return [pscustomobject]@{
            CreateTag          = $false
            PushTag            = $false
            ReusedExistingTag  = $true
        }
    }

    if ($Local.Exists) {
        return [pscustomobject]@{
            CreateTag          = $false
            PushTag            = $true
            ReusedExistingTag  = $true
        }
    }

    return [pscustomobject]@{
        CreateTag          = $true
        PushTag            = $true
        ReusedExistingTag  = $false
    }
}

function Get-HermesReleaseView {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    $result = Invoke-HermesTool `
        -Context $Context `
        -Name "gh" `
        -ArgumentList @(
            "release", "view", $Tag,
            "--repo", $script:HermesReleaseSlug,
            "--json", "tagName,name,isDraft,isPrerelease,url"
        ) `
        -AllowFailure

    if ([int]$result.ExitCode -ne 0) {
        return [pscustomobject]@{
            Exists       = $false
            TagName      = $null
            IsDraft      = $false
            IsPrerelease = $false
            Url          = $null
        }
    }

    $view = $result.Stdout | ConvertFrom-Json
    return [pscustomobject]@{
        Exists       = $true
        TagName      = [string]$view.tagName
        IsDraft      = [bool]$view.isDraft
        IsPrerelease = [bool]$view.isPrerelease
        Url          = [string]$view.url
    }
}

function Assert-HermesExactMainCiSuccess {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha
    )

    $result = Invoke-HermesTool `
        -Context $Context `
        -Name "gh" `
        -ArgumentList @(
            "run", "list",
            "--repo", $script:HermesReleaseSlug,
            "--workflow", $script:HermesReleaseWorkflow,
            "--commit", $ExpectedSha,
            "--limit", "50",
            "--json", "databaseId,headSha,status,conclusion,event,headBranch,workflowName,url,name"
        )

    $runs = @(Convert-HermesJsonArray -Stdout $result.Stdout -Label "gh run list")
    $exactMain = @()
    foreach ($run in $runs) {
        $runSha = ([string]$run.headSha).ToLowerInvariant()
        if (
            $runSha -eq $ExpectedSha -and
            [string]$run.event -eq "push" -and
            [string]$run.headBranch -eq "main"
        ) {
            $exactMain += $run
        }
    }

    if ($exactMain.Count -eq 0) {
        throw "No exact-main GitHub Actions CI run found for commit $ExpectedSha (workflow $($script:HermesReleaseWorkflow), event push, branch main). Latest-branch green is not enough."
    }

    $successful = @()
    foreach ($run in $exactMain) {
        if ([string]$run.status -eq "completed" -and [string]$run.conclusion -eq "success") {
            $successful += $run
        }
    }

    if ($successful.Count -eq 0) {
        $sample = $exactMain[0]
        throw "Exact-main CI for $ExpectedSha is not completed/success (status=$($sample.status), conclusion=$($sample.conclusion)). Refusing to publish."
    }
}

function Invoke-HermesRelease {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedMainSha,
        [Parameter(Mandatory = $true)]
        [string]$ReleaseNotes,
        [string]$Title,
        [string]$RepoRoot,
        [scriptblock]$CommandRunner,
        [scriptblock]$CommandResolver
    )

    if ($null -eq $CommandRunner) {
        throw "CommandRunner is required. scripts/release.ps1 supplies the real runner; tests must inject a fake."
    }

    Write-HermesReleaseStep "Validating version, SHA and release notes"
    $tag = Get-HermesCanonicalTagName -Version $Version
    $expected = Get-HermesNormalizedCommitSha -Sha $ExpectedMainSha -Label "ExpectedMainSha"
    $notesPath = Resolve-HermesReleaseNotesPath -ReleaseNotes $ReleaseNotes
    $versionBare = $tag.Substring(1)
    if ([string]::IsNullOrWhiteSpace($Title)) {
        $Title = "Hermes Finance $versionBare"
    }

    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    }
    else {
        $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
    }

    if ($null -eq $CommandResolver) {
        $CommandResolver = New-HermesDefaultCommandResolver
    }

    $gitPath = Resolve-HermesToolPath -CommandResolver $CommandResolver -Name "git" -InstallHint "Missing dependency 'git'. Install Git for Windows and retry."
    $ghPath = Resolve-HermesToolPath -CommandResolver $CommandResolver -Name "gh" -InstallHint "Missing dependency 'gh'. Install GitHub CLI from https://cli.github.com/ and run 'gh auth login'. The release helper will not fall back to API token scraping or .env files."

    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
        throw "Repository metadata not found at '$RepoRoot'. Run scripts/release.ps1 from the Hermes Finance checkout."
    }

    $context = [pscustomobject]@{
        RepoRoot       = $RepoRoot
        CommandRunner  = $CommandRunner
        GitPath        = $gitPath
        GhPath         = $ghPath
    }

    Write-HermesReleaseStep "Resolving LTstripes/hermes-finance checkout"
    $topLevel = Invoke-HermesTool `
        -Context $context `
        -Name "git" `
        -ArgumentList @("-C", $RepoRoot, "rev-parse", "--show-toplevel")
    $resolvedTop = [IO.Path]::GetFullPath($topLevel.Stdout.Trim()).TrimEnd("\")
    $resolvedRoot = $RepoRoot.TrimEnd("\")
    if ($resolvedTop -ine $resolvedRoot) {
        throw "Git toplevel '$resolvedTop' does not match release helper root '$resolvedRoot'."
    }

    $origin = Invoke-HermesTool `
        -Context $context `
        -Name "git" `
        -ArgumentList @("-C", $RepoRoot, "remote", "get-url", "origin")
    Test-HermesExpectedGitHubRemote -Url $origin.Stdout.Trim()

    Write-HermesReleaseStep "Checking GitHub CLI authentication"
    $auth = Invoke-HermesTool `
        -Context $context `
        -Name "gh" `
        -ArgumentList @("auth", "status") `
        -AllowFailure
    if ([int]$auth.ExitCode -ne 0) {
        throw "GitHub CLI is not authenticated. Run 'gh auth login' for LTstripes/hermes-finance and retry. The release helper will not read tokens from .env or other files."
    }

    Write-HermesReleaseStep "Fetching origin/main before deciding"
    $null = Invoke-HermesTool `
        -Context $context `
        -Name "git" `
        -ArgumentList @("-C", $RepoRoot, "fetch", "origin", "refs/heads/main:refs/remotes/origin/main")

    $originMain = Invoke-HermesTool `
        -Context $context `
        -Name "git" `
        -ArgumentList @("-C", $RepoRoot, "rev-parse", "--verify", "refs/remotes/origin/main")
    $originMainSha = Get-HermesNormalizedCommitSha -Sha $originMain.Stdout.Trim() -Label "origin/main"
    if ($originMainSha -ne $expected) {
        throw "origin/main is $originMainSha, not ExpectedMainSha $expected. Refusing to publish. Fetch completed; no tag or GitHub Release was created."
    }

    Write-HermesReleaseStep "Checking local and remote tag $tag"
    $localTag = Get-HermesLocalTagInfo -Context $context -Tag $tag
    $remoteTag = Get-HermesRemoteTagInfo -Context $context -Tag $tag
    $tagPlan = Resolve-HermesTagPlan -Local $localTag -Remote $remoteTag -ExpectedSha $expected -Tag $tag

    Write-HermesReleaseStep "Checking exact-main GitHub Actions CI"
    Assert-HermesExactMainCiSuccess -Context $context -ExpectedSha $expected

    $tagCreated = $false
    $tagPushed = $false
    $releaseCreated = $false
    $remotePublished = [bool]$remoteTag.Exists

    if ([bool]$tagPlan.CreateTag) {
        Write-HermesReleaseStep "Creating annotated tag $tag on $expected"
        $null = Invoke-HermesTool `
            -Context $context `
            -Name "git" `
            -ArgumentList @("-C", $RepoRoot, "tag", "-a", $tag, "-m", $Title, $expected)
        $tagCreated = $true
    }
    elseif ([bool]$tagPlan.ReusedExistingTag) {
        Write-HermesReleaseStep "Reusing existing annotated tag $tag at $expected"
    }

    if ([bool]$tagPlan.PushTag) {
        Write-HermesReleaseStep "Pushing only refs/tags/$tag"
        try {
            $null = Invoke-HermesTool `
                -Context $context `
                -Name "git" `
                -ArgumentList @("-C", $RepoRoot, "push", "origin", "refs/tags/${tag}:refs/tags/$tag")
            $tagPushed = $true
            $remotePublished = $true
        }
        catch {
            throw "Failed to push tag $tag. Local tag was not deleted or moved. $($_.Exception.Message)"
        }
    }

    Write-HermesReleaseStep "Reading back remote tag $tag"
    $remoteAfter = Get-HermesRemoteTagInfo -Context $context -Tag $tag
    if (-not [bool]$remoteAfter.Exists) {
        throw "Remote tag $tag is missing after the tag step. Refusing to create a GitHub Release from a branch."
    }
    if (-not [bool]$remoteAfter.Annotated) {
        throw "Remote tag $tag is not annotated after the tag step. Refusing to continue."
    }
    if ([string]$remoteAfter.Sha -ne $expected) {
        throw "Remote tag $tag peeled to $($remoteAfter.Sha), not $expected. Refusing to create a GitHub Release."
    }
    $remotePublished = $true

    Write-HermesReleaseStep "Checking GitHub Release $tag"
    $releaseView = Get-HermesReleaseView -Context $context -Tag $tag
    if ([bool]$releaseView.Exists) {
        if ([bool]$releaseView.IsDraft) {
            throw "GitHub Release $tag already exists as a draft. Refusing to auto-publish or rewrite it."
        }
        if ([bool]$releaseView.IsPrerelease) {
            throw "GitHub Release $tag already exists as a prerelease. Refusing to rewrite it."
        }
        if ([string]$releaseView.TagName -ne $tag) {
            throw "GitHub Release tag '$($releaseView.TagName)' does not match $tag."
        }
    }
    else {
        Write-HermesReleaseStep "Creating published GitHub Release from existing tag $tag"
        try {
            $null = Invoke-HermesTool `
                -Context $context `
                -Name "gh" `
                -ArgumentList @(
                    "release", "create", $tag,
                    "--repo", $script:HermesReleaseSlug,
                    "--title", $Title,
                    "--notes-file", $notesPath,
                    "--verify-tag"
                )
            $releaseCreated = $true
        }
        catch {
            if ($remotePublished) {
                throw "PARTIAL: tag $tag is on origin at $expected. GitHub Release was not created. $($_.Exception.Message) Re-run the same command to create the Release; the helper will not move or delete the tag."
            }
            throw
        }
    }

    Write-HermesReleaseStep "Final read-back of tag and GitHub Release"
    $finalTag = Get-HermesRemoteTagInfo -Context $context -Tag $tag
    if (-not [bool]$finalTag.Exists -or -not [bool]$finalTag.Annotated -or [string]$finalTag.Sha -ne $expected) {
        throw "Final tag read-back failed for $tag. Expected annotated tag at $expected."
    }

    $finalRelease = Get-HermesReleaseView -Context $context -Tag $tag
    if (-not [bool]$finalRelease.Exists) {
        throw "PARTIAL: tag $tag is on origin at $expected. GitHub Release is still missing after the create step. Re-run the same command; the helper will not move or delete the tag."
    }
    if ([bool]$finalRelease.IsDraft -or [bool]$finalRelease.IsPrerelease) {
        throw "GitHub Release $tag read-back is draft=$($finalRelease.IsDraft) prerelease=$($finalRelease.IsPrerelease). Expected a published non-prerelease."
    }
    if ([string]$finalRelease.TagName -ne $tag) {
        throw "GitHub Release read-back tag '$($finalRelease.TagName)' does not match $tag."
    }

    return [pscustomobject]@{
        Version           = $versionBare
        Tag               = $tag
        Sha               = $expected
        Title             = $Title
        ReleaseNotes      = $notesPath
        ReleaseUrl        = $finalRelease.Url
        TagCreated        = $tagCreated
        TagPushed         = $tagPushed
        ReleaseCreated    = $releaseCreated
        ReusedExistingTag = [bool]$tagPlan.ReusedExistingTag
    }
}
