# GitHub-native release request validation for Hermes Finance.
# This layer validates the narrow owner trigger and repository release identity.
# Publication itself stays in scripts/release-lib.ps1 so the manual fallback and
# GitHub-native automation share the same guarded release semantics.

Set-StrictMode -Version 2.0

$script:HermesReleaseControlRepository = "LTstripes/hermes-finance"
$script:HermesReleaseControlOwner = "LTstripes"

function Get-HermesReleaseRequest {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$RequestBody
    )

    $lines = @($RequestBody -split "\r?\n")
    while ($lines.Count -gt 0 -and [string]::IsNullOrWhiteSpace([string]$lines[$lines.Count - 1])) {
        if ($lines.Count -eq 1) {
            $lines = @()
        }
        else {
            $lines = @($lines[0..($lines.Count - 2)])
        }
    }

    if ($lines.Count -ne 3) {
        throw "Release request must contain exactly three non-trailing lines: /release, version=X.Y.Z, expected_main_sha=<40-hex>."
    }
    if ([string]$lines[0] -ne "/release") {
        throw "Release request first line must be exactly '/release'."
    }
    if ([string]$lines[1] -notmatch "^version=(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") {
        throw "Release request version line must be exactly version=X.Y.Z with no prefix or suffix."
    }
    $version = ([string]$lines[1]).Substring("version=".Length)

    if ([string]$lines[2] -notmatch "^expected_main_sha=([0-9a-fA-F]{40})$") {
        throw "Release request expected_main_sha must be the full 40-character commit SHA."
    }
    $sha = $Matches[1].ToLowerInvariant()

    return [pscustomobject]@{
        Version         = $version
        ExpectedMainSha = $sha
        Tag             = "v$version"
    }
}

function Assert-HermesReleaseRequestProvenance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repository,
        [Parameter(Mandatory = $true)]
        [string]$Actor,
        [Parameter(Mandatory = $true)]
        [string]$CommentAuthor,
        [Parameter(Mandatory = $true)]
        [int]$IssueNumber,
        [Parameter(Mandatory = $true)]
        [int]$ControlIssueNumber,
        [Parameter(Mandatory = $true)]
        [string]$EventName,
        [Parameter(Mandatory = $true)]
        [string]$EventAction
    )

    if ($Repository -ine $script:HermesReleaseControlRepository) {
        throw "Release request repository '$Repository' is not $($script:HermesReleaseControlRepository)."
    }
    if ($EventName -ne "issue_comment" -or $EventAction -ne "created") {
        throw "Release request must come from an issue_comment/created event."
    }
    if ($IssueNumber -ne $ControlIssueNumber) {
        throw "Release request came from issue #$IssueNumber; only control issue #$ControlIssueNumber is allowed."
    }
    if ($Actor -ine $script:HermesReleaseControlOwner) {
        throw "Release request actor '$Actor' is not the repository owner."
    }
    if ($CommentAuthor -ine $script:HermesReleaseControlOwner) {
        throw "Release request comment author '$CommentAuthor' is not the repository owner."
    }
}

function Get-HermesProjectVersionFromPyproject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $content = [IO.File]::ReadAllText($Path)
    $match = [regex]::Match(
        $content,
        '(?ms)^\[project\]\s*(?:(?!^\[).)*?^version\s*=\s*"([^"]+)"\s*$'
    )
    if (-not $match.Success) {
        throw "Unable to resolve [project].version from '$Path'."
    }
    return [string]$match.Groups[1].Value
}

function Get-HermesPackageVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $content = [IO.File]::ReadAllText($Path)
    $match = [regex]::Match($content, '(?m)^__version__\s*=\s*"([^"]+)"\s*$')
    if (-not $match.Success) {
        throw "Unable to resolve __version__ from '$Path'."
    }
    return [string]$match.Groups[1].Value
}

function Assert-HermesReleaseIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    $root = [IO.Path]::GetFullPath($RepoRoot)
    $pyprojectPath = Join-Path $root "backend\pyproject.toml"
    $packagePath = Join-Path $root "backend\src\hermes_finance\__init__.py"
    $notesPath = Join-Path $root ("docs\release-notes-{0}.md" -f $Version)

    foreach ($required in @($pyprojectPath, $packagePath, $notesPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required release identity file is missing: $required"
        }
    }

    $projectVersion = Get-HermesProjectVersionFromPyproject -Path $pyprojectPath
    if ($projectVersion -ne $Version) {
        throw "backend/pyproject.toml version is '$projectVersion', not requested version '$Version'."
    }

    $packageVersion = Get-HermesPackageVersion -Path $packagePath
    if ($packageVersion -ne $Version) {
        throw "hermes_finance.__version__ is '$packageVersion', not requested version '$Version'."
    }

    $notes = Get-Item -LiteralPath $notesPath
    if ($notes.Length -le 0) {
        throw "Canonical release notes are empty: $notesPath"
    }

    return [pscustomobject]@{
        Version        = $Version
        ProjectVersion = $projectVersion
        PackageVersion = $packageVersion
        ReleaseNotes   = $notesPath
    }
}
function Submit-HermesReleaseRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$DryRun,
        [scriptblock]$CommandRunner = (New-HermesDefaultCommandRunner),
        [scriptblock]$CommandResolver = (New-HermesDefaultCommandResolver),
        [ValidateRange(1, 120)][int]$PollAttempts = 30,
        [scriptblock]$PollWait = { Start-Sleep -Seconds 2 }
    )

    # Validate grammar before resolving tools or making any network request.
    $null = Get-HermesReleaseRequest -RequestBody ("/release" + "`nversion=$Version`nexpected_main_sha=" + ("0" * 40))
    $context = [pscustomobject]@{
        GitPath = Resolve-HermesToolPath -Name "git" -CommandResolver $CommandResolver -InstallHint "Install git."
        GhPath = Resolve-HermesToolPath -Name "gh" -CommandResolver $CommandResolver -InstallHint "Install gh."
        RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
        CommandRunner = $CommandRunner
    }
    $origin = Invoke-HermesTool -Context $context -Name git -ArgumentList @("-C", $context.RepoRoot, "remote", "get-url", "--all", "origin")
    $urls = Convert-HermesMultilineUrls -Stdout $origin.Stdout
    if (@($urls.Urls).Count -ne 1) { throw "Expected one canonical origin URL." }
    $null = Test-HermesExpectedGitHubRemote -Url $urls.Urls[0]
    $main = Invoke-HermesTool -Context $context -Name git -ArgumentList @("-C", $context.RepoRoot, "ls-remote", "origin", "refs/heads/main")
    $sha = Get-HermesLsRemoteSha -Stdout $main.Stdout
    $sha = Get-HermesNormalizedCommitSha -Sha $sha
    Assert-HermesExactMainCiSuccess -Context $context -ExpectedSha $sha
    $notes = Invoke-HermesTool -Context $context -Name gh -ArgumentList @("api", "repos/$script:HermesReleaseControlRepository/contents/docs/release-notes-$Version.md?ref=$sha")
    $file = $notes.Stdout | ConvertFrom-Json
    if ($file.type -ne "file" -or [long]$file.size -le 0) { throw "Canonical release notes must be a nonempty file on main." }
    $body = "/release`nversion=$Version`nexpected_main_sha=$sha"
    Write-Host "Checks passed: canonical origin/main $sha; completed successful ci.yml push; notes on exact main."
    if ($DryRun) {
        Write-Output $body
        return
    }
    $user = Invoke-HermesTool -Context $context -Name gh -ArgumentList @("api", "user", "--jq", ".login")
    if ($user.Stdout.Trim() -ine $script:HermesReleaseControlOwner) { throw "Release request must be posted by the repository owner." }

    $runArgs = @("api", "repos/$script:HermesReleaseControlRepository/actions/workflows/release.yml/runs?event=issue_comment&per_page=100")
    $before = Invoke-HermesTool -Context $context -Name gh -ArgumentList $runArgs
    $known = @(($before.Stdout | ConvertFrom-Json).workflow_runs | ForEach-Object { [string]$_.id })
    $started = [DateTimeOffset]::UtcNow
    $temp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($temp, $body, (New-Object Text.UTF8Encoding $false))
        # No body text is ever passed as a shell argument. Never retry this mutation.
        $posted = Invoke-HermesTool -Context $context -Name gh -ArgumentList @("issue", "comment", "124", "--repo", $script:HermesReleaseControlRepository, "--body-file", $temp)
        $url = $posted.Stdout.Trim()
        Write-Host "Comment: $url"
    }
    finally {
        Remove-Item -LiteralPath $temp -Force
    }
    for ($attempt = 0; $attempt -lt $PollAttempts; $attempt++) {
        $after = Invoke-HermesTool -Context $context -Name gh -ArgumentList $runArgs
        $runs = @(($after.Stdout | ConvertFrom-Json).workflow_runs | Where-Object {
            [string]$_.id -notin $known -and $_.event -eq "issue_comment" -and
            $_.head_sha -eq $sha -and $_.actor.login -ieq $script:HermesReleaseControlOwner -and
            [DateTimeOffset]$_.created_at -ge $started.AddSeconds(-2)
        })
        if ($runs.Count -gt 1) { throw "Comment posted at $url; multiple new release runs observed; inspect them before proceeding. Do not repost." }
        if ($runs.Count -eq 1) {
            $jobsResult = Invoke-HermesTool -Context $context -Name gh -ArgumentList @("api", "repos/$script:HermesReleaseControlRepository/actions/runs/$($runs[0].id)/jobs")
            $jobs = @(($jobsResult.Stdout | ConvertFrom-Json).jobs | Where-Object { $_.name -eq "Guarded release" })
            if ($jobs.Count -eq 1) {
                if ($jobs[0].conclusion -eq "skipped") {
                    throw "Comment posted at $url; Guarded release job was skipped: $($runs[0].html_url). Inspect before proceeding; do not repost."
                }
                Write-Host "Guarded Release: $($runs[0].html_url)"
                return
            }
        }
        if ($attempt + 1 -lt $PollAttempts) { & $PollWait }
    }
    throw "Comment posted at $url; Guarded Release run not observed within the wait window. Inspect Actions; do not repost."
}
