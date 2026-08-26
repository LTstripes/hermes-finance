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
