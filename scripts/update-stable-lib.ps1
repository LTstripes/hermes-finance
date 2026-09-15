# Composable explicit Stable release update operation for Hermes Finance.
# The public entrypoint is scripts/update-stable.ps1.  This library keeps the
# operation testable without making the launcher or a mutable Stable checkout
# the owner of the update state machine.

Set-StrictMode -Version 2.0

function Convert-HermesStableVersionParts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $tag = Get-HermesCanonicalTagName -Version $Version
    $parts = $tag.Substring(1).Split(".")
    return [pscustomobject]@{
        Tag   = $tag
        Major = [int]$parts[0]
        Minor = [int]$parts[1]
        Patch = [int]$parts[2]
        Text  = $tag.Substring(1)
        Label = $Label
    }
}

function Compare-HermesStableVersion {
    param(
        [Parameter(Mandatory = $true)]
        $Left,
        [Parameter(Mandatory = $true)]
        $Right
    )

    foreach ($field in @("Major", "Minor", "Patch")) {
        if ([int]$Left.$field -lt [int]$Right.$field) {
            return -1
        }
        if ([int]$Left.$field -gt [int]$Right.$field) {
            return 1
        }
    }

    return 0
}

function Resolve-HermesStableInputPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,
        [Parameter(Mandatory = $true)]
        [string]$BaseDirectory,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Label is required."
    }

    $candidate = $Value.Trim()
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $BaseDirectory $candidate
    }

    try {
        return [IO.Path]::GetFullPath($candidate)
    }
    catch {
        throw "$Label is not a valid path."
    }
}

function Get-HermesStableCommandPath {
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

function Invoke-HermesStableExternalCommand {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @(),
        [switch]$AllowFailure
    )

    $request = [pscustomobject]@{
        Name      = $Name
        FileName  = $FilePath
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

function Invoke-HermesStableGit {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @(),
        [switch]$AllowFailure
    )

    return Invoke-HermesTool `
        -Context $Context `
        -Name "git" `
        -ArgumentList @($ArgumentList) `
        -AllowFailure:$AllowFailure
}

function Get-HermesStableGitText {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @()
    )

    $result = Invoke-HermesStableGit -Context $Context -ArgumentList $ArgumentList
    return [string]$result.Stdout
}

function Get-HermesStableNullSeparatedItems {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    if ([string]::IsNullOrEmpty($Text)) {
        return @()
    }

    return @(
        $Text -split [char]0 |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            ForEach-Object { [string]$_ }
    )
}

function Get-HermesStableNormalizedGitPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $normalized = $Path.Trim().Replace("\", "/")
    while ($normalized.StartsWith("./", [StringComparison]::Ordinal)) {
        $normalized = $normalized.Substring(2)
    }
    return $normalized.ToLowerInvariant()
}

function Get-HermesStableRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if ($resolvedPath -ieq $resolvedRoot) {
        return ""
    }

    $prefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }

    return $resolvedPath.Substring($prefix.Length).Replace("\", "/")
}

function Test-HermesStablePathRelation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Left,
        [Parameter(Mandatory = $true)]
        [string]$Right
    )

    $leftPath = Get-HermesStableNormalizedGitPath -Path $Left
    $rightPath = Get-HermesStableNormalizedGitPath -Path $Right
    return (
        $leftPath -eq $rightPath -or
        $leftPath.StartsWith($rightPath + "/", [StringComparison]::Ordinal) -or
        $rightPath.StartsWith($leftPath + "/", [StringComparison]::Ordinal)
    )
}

function Assert-HermesStableNoReparsePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [switch]$AllowMissingLeaf
    )

    $current = [IO.Path]::GetFullPath($Path)
    $missingLeaf = $false
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $exists = Test-Path -LiteralPath $current
        if (-not $exists) {
            if (-not $missingLeaf -and $AllowMissingLeaf) {
                $missingLeaf = $true
            }
            elseif (-not $missingLeaf) {
                throw "$Label does not exist: $Path"
            }
            $parent = Split-Path -Parent $current
            if ($parent -eq $current) {
                break
            }
            $current = $parent
            continue
        }

        $item = Get-Item -LiteralPath $current
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label uses a reparse point; update is blocked."
        }

        $parent = Split-Path -Parent $current
        if ($parent -eq $current) {
            break
        }
        $current = $parent
    }
}

function Resolve-HermesStableDataPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StableCheckout,
        [string]$DatabasePath,
        [string]$BackupDirectory
    )

    $databaseValue = $DatabasePath
    if ([string]::IsNullOrWhiteSpace($databaseValue)) {
        $databaseValue = [Environment]::GetEnvironmentVariable("HERMES_FINANCE_DATABASE_PATH", "Process")
    }
    if ([string]::IsNullOrWhiteSpace($databaseValue)) {
        $databaseValue = Join-Path $StableCheckout "data\finance.db"
    }
    elseif (-not [IO.Path]::IsPathRooted($databaseValue)) {
        throw "HERMES_FINANCE_DATABASE_PATH must be an absolute path when supplied."
    }

    $database = Resolve-HermesStableInputPath `
        -Value $databaseValue `
        -BaseDirectory $StableCheckout `
        -Label "Stable database path"

    $backupValue = $BackupDirectory
    if ([string]::IsNullOrWhiteSpace($backupValue)) {
        $backupValue = Join-Path (Split-Path -Parent $database) "backups"
    }
    $backup = Resolve-HermesStableInputPath `
        -Value $backupValue `
        -BaseDirectory $StableCheckout `
        -Label "Stable backup directory"

    if ($database -ieq $backup) {
        throw "Stable database path and backup directory must be different."
    }
    if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
        throw "Stable production database is not a regular file; refusing to guess a data source."
    }
    Assert-HermesStableNoReparsePath -Path $database -Label "Stable production database"
    Assert-HermesStableNoReparsePath -Path (Split-Path -Parent $database) -Label "Stable database directory"

    if (Test-Path -LiteralPath $backup) {
        if (-not (Test-Path -LiteralPath $backup -PathType Container)) {
            throw "Stable backup directory is not a directory."
        }
        Assert-HermesStableNoReparsePath -Path $backup -Label "Stable backup directory"
    }
    else {
        Assert-HermesStableNoReparsePath `
            -Path (Split-Path -Parent $backup) `
            -Label "Stable backup parent"
    }

    return [pscustomobject]@{
        Database = $database
        Backup   = $backup
    }
}

function Assert-HermesStablePortFree {
    $listeners = $null
    try {
        $listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    }
    catch {
        throw "Cannot prove that Stable runtime port 8000 is free; update is blocked."
    }

    foreach ($listener in @($listeners)) {
        if ($listener.Port -eq 8000) {
            throw "Stable runtime is running or port 8000 is occupied; stop it before updating."
        }
    }
}

function Get-HermesStableCheckoutState {
    param(
        [Parameter(Mandatory = $true)]
        $Context
    )

    $topLevel = Get-HermesStableGitText -Context $Context -ArgumentList @("-C", $Context.RepoRoot, "rev-parse", "--show-toplevel")
    if ([string]::IsNullOrWhiteSpace($topLevel)) {
        throw "Stable path is not a valid Git checkout."
    }
    $resolvedTop = [IO.Path]::GetFullPath($topLevel.Trim()).TrimEnd("\", "/")
    $resolvedRoot = [IO.Path]::GetFullPath([string]$Context.RepoRoot).TrimEnd("\", "/")
    if ($resolvedTop -ine $resolvedRoot) {
        throw "Stable Git toplevel does not match the explicitly selected checkout."
    }

    $head = Get-HermesStableGitText -Context $Context -ArgumentList @("-C", $Context.RepoRoot, "rev-parse", "--verify", "HEAD")
    $head = $head.Trim().ToLowerInvariant()
    if ($head -notmatch "^[0-9a-f]{40}$") {
        throw "Stable checkout HEAD cannot be proven as a full commit identity."
    }

    $status = Get-HermesStableGitText `
        -Context $Context `
        -ArgumentList @("-C", $Context.RepoRoot, "status", "--porcelain=v1", "--untracked-files=all")
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "Stable checkout has uncommitted or untracked development changes; update is blocked."
    }

    $tagsText = Get-HermesStableGitText `
        -Context $Context `
        -ArgumentList @(
            "-C", $Context.RepoRoot,
            "for-each-ref",
            "--format=%(refname:strip=2)",
            "--points-at", "HEAD",
            "refs/tags"
        )
    $tags = @(
        $tagsText -split "\r?\n" |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ -match "^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$" } |
            Select-Object -Unique
    )

    return [pscustomobject]@{
        Head = $head
        Tags = $tags
    }
}

function Assert-HermesStableOrigin {
    param(
        [Parameter(Mandatory = $true)]
        $Context
    )

    $result = Invoke-HermesStableGit `
        -Context $Context `
        -ArgumentList @("-C", $Context.RepoRoot, "remote", "get-url", "--all", "origin")
    $parsedUrls = Convert-HermesMultilineUrls -Stdout ([string]$result.Stdout)
    $urls = @($parsedUrls.Urls)
    if ($urls.Count -eq 0) {
        throw "origin has no fetch URL; expected LTstripes/hermes-finance."
    }
    foreach ($url in $urls) {
        Test-HermesExpectedGitHubRemote -Url $url
    }

    Assert-HermesOriginNotMirror -Context $Context
    $Context.PushUrl = [string]$urls[0]
}

function Assert-HermesStableCurrentRelease {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $CheckoutState
    )

    $candidateTags = @($CheckoutState.Tags)
    if ($candidateTags.Count -eq 0) {
        throw "Stable current identity is not an immutable vX.Y.Z release tag; update is blocked."
    }
    if ($candidateTags.Count -ne 1) {
        throw "Stable current release identity is ambiguous; update is blocked."
    }

    $tag = [string]$candidateTags[0]
    $local = Get-HermesLocalTagInfo -Context $Context -Tag $tag
    if (-not [bool]$local.Exists -or -not [bool]$local.Annotated) {
        throw "Stable current release tag $tag is not an annotated local tag; update is blocked."
    }
    if ([string]$local.Sha -ne [string]$CheckoutState.Head) {
        throw "Stable current release tag $tag does not prove the current checkout HEAD."
    }

    $remote = Get-HermesRemoteTagInfo -Context $Context -Tag $tag
    if (-not [bool]$remote.Exists -or -not [bool]$remote.Annotated) {
        throw "Stable current release tag $tag is not a published annotated remote tag."
    }
    if ([string]$remote.Sha -ne [string]$CheckoutState.Head) {
        throw "Stable current release tag $tag does not prove the current checkout commit."
    }

    $release = Get-HermesReleaseView -Context $Context -Tag $tag
    if (-not [bool]$release.Exists) {
        throw "Stable current release $tag is not a published GitHub Release."
    }
    if ([bool]$release.IsDraft -or [bool]$release.IsPrerelease) {
        throw "Stable current release $tag is draft or prerelease; update is blocked."
    }
    if ([string]$release.TagName -ne $tag) {
        throw "Stable current GitHub Release tag '$($release.TagName)' does not match $tag."
    }

    $version = Convert-HermesStableVersionParts -Version $tag -Label "current Stable release"
    return [pscustomobject]@{
        Tag       = $tag
        Version   = $version
        CommitSha = [string]$CheckoutState.Head
        Release   = $release
    }
}

function Assert-HermesStableTargetRelease {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Tag,
        [Parameter(Mandatory = $true)]
        $Version
    )

    $remote = Get-HermesRemoteTagInfo -Context $Context -Tag $Tag
    if (-not [bool]$remote.Exists) {
        throw "Target release $Tag is not present as an immutable remote tag."
    }
    if (-not [bool]$remote.Annotated) {
        throw "Target release $Tag exists but is not an annotated tag."
    }
    if ([string]::IsNullOrWhiteSpace([string]$remote.Sha)) {
        throw "Target release $Tag has no exact peeled commit SHA."
    }

    $release = Get-HermesReleaseView -Context $Context -Tag $Tag
    if (-not [bool]$release.Exists) {
        throw "Target release $Tag is not a published GitHub Release."
    }
    if ([bool]$release.IsDraft) {
        throw "Target release $Tag is a draft GitHub Release."
    }
    if ([bool]$release.IsPrerelease) {
        throw "Target release $Tag is a prerelease GitHub Release."
    }
    if ([string]$release.TagName -ne $Tag) {
        throw "Target GitHub Release tag '$($release.TagName)' does not match $Tag."
    }

    return [pscustomobject]@{
        Tag       = $Tag
        Version   = $Version
        CommitSha = [string]$remote.Sha
        Release   = $release
    }
}

function Assert-HermesStableLocalTargetBeforeBackup {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $Target
    )

    $local = Get-HermesLocalTagInfo -Context $Context -Tag $Target.Tag
    if (-not [bool]$local.Exists) {
        return
    }
    if (-not [bool]$local.Annotated) {
        throw "Local target tag $($Target.Tag) exists but is not annotated."
    }
    if ([string]$local.Sha -ne [string]$Target.CommitSha) {
        throw "Local target tag $($Target.Tag) points to a different commit; update is blocked."
    }
}

function Assert-HermesStableFetchedTarget {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $Target
    )

    $local = Get-HermesLocalTagInfo -Context $Context -Tag $Target.Tag
    if (-not [bool]$local.Exists -or -not [bool]$local.Annotated) {
        throw "Fetched target tag $($Target.Tag) is not an annotated local tag."
    }
    if ([string]$local.Sha -ne [string]$Target.CommitSha) {
        throw "Fetched target tag $($Target.Tag) does not peel to the proven release commit."
    }
}

function Get-HermesStableTargetBlob {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$CommitSha,
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $object = "{0}:{1}" -f $CommitSha, $RelativePath
    return Get-HermesStableGitText -Context $Context -ArgumentList @("-C", $Context.RepoRoot, "show", $object)
}

function Test-HermesStablePrivateOrRuntimePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return (
        $Path -eq ".env" -or
        ($Path.StartsWith(".env.", [StringComparison]::Ordinal) -and $Path -ne ".env.example") -or
        $Path -eq "backend/.venv" -or
        $Path.StartsWith("backend/.venv/", [StringComparison]::Ordinal) -or
        $Path -eq "frontend/node_modules" -or
        $Path.StartsWith("frontend/node_modules/", [StringComparison]::Ordinal) -or
        $Path -eq "frontend/dist" -or
        $Path.StartsWith("frontend/dist/", [StringComparison]::Ordinal) -or
        $Path.StartsWith(".hermes-runtime-prepared.json", [StringComparison]::Ordinal)
    )
}

function Assert-HermesStableTargetCodeIdentity {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $Target
    )

    $packageText = Get-HermesStableTargetBlob `
        -Context $Context `
        -CommitSha $Target.CommitSha `
        -RelativePath "backend/src/hermes_finance/__init__.py"
    $packageMatch = [regex]::Match($packageText, '(?m)^__version__\s*=\s*"([^"]+)"\s*$')
    if (-not $packageMatch.Success -or $packageMatch.Groups[1].Value -ne $Target.Version.Text) {
        throw "Target release $($Target.Tag) commit does not contain the requested backend version."
    }

    $projectText = Get-HermesStableTargetBlob `
        -Context $Context `
        -CommitSha $Target.CommitSha `
        -RelativePath "backend/pyproject.toml"
    $projectMatch = [regex]::Match(
        $projectText,
        '(?ms)^\[project\]\s*(?:(?!^\[).)*?^version\s*=\s*"([^"]+)"\s*$'
    )
    if (-not $projectMatch.Success -or $projectMatch.Groups[1].Value -ne $Target.Version.Text) {
        throw "Target release $($Target.Tag) commit does not contain the requested project version."
    }

    $notesObject = "{0}:docs/release-notes-{1}.md" -f $Target.CommitSha, $Target.Version.Text
    $notes = Invoke-HermesStableGit `
        -Context $Context `
        -ArgumentList @("-C", $Context.RepoRoot, "cat-file", "-e", $notesObject) `
        -AllowFailure
    if ([int]$notes.ExitCode -ne 0) {
        throw "Target release $($Target.Tag) commit is missing canonical release notes."
    }
}

function Get-HermesStableTrackedPaths {
    param(
        [Parameter(Mandatory = $true)]
        $Context
    )

    return @(
        Get-HermesStableNullSeparatedItems -Text (
            Get-HermesStableGitText `
                -Context $Context `
                -ArgumentList @("-C", $Context.RepoRoot, "ls-files", "-z")
        ) |
            ForEach-Object { Get-HermesStableNormalizedGitPath -Path $_ }
    )
}

function Assert-HermesStableTrackedPathSafety {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $DataPaths,
        [Parameter(Mandatory = $true)]
        [string[]]$Paths,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    foreach ($path in @($Paths)) {
        if ($path -eq "data/.gitkeep") {
            $gitObject = "HEAD:{0}" -f $path
            $sizeResult = Invoke-HermesStableGit `
                -Context $Context `
                -ArgumentList @("-C", $Context.RepoRoot, "cat-file", "-s", $gitObject)
            $size = 0L
            if (-not [long]::TryParse(([string]$sizeResult.Stdout).Trim(), [ref]$size) -or $size -ne 0) {
                throw "$Label data/.gitkeep is not an empty placeholder; update is blocked."
            }
            continue
        }
        if ($path -eq "data" -or $path.StartsWith("data/", [StringComparison]::Ordinal)) {
            throw "$Label contains a tracked production-data path; update is blocked."
        }
        if (Test-HermesStablePrivateOrRuntimePath -Path $path) {
            throw "$Label contains a tracked runtime/private path; update is blocked."
        }
    }

    $databaseRelative = $null
    try {
        $databaseRelative = Get-HermesStableNormalizedGitPath `
            -Path (Get-HermesStableRelativePath -Root $Context.RepoRoot -Path $DataPaths.Database)
    }
    catch {
        $databaseRelative = $null
    }
    if (-not [string]::IsNullOrWhiteSpace($databaseRelative)) {
        foreach ($path in @($Paths)) {
            if ($path -ne "data/.gitkeep" -and (Test-HermesStablePathRelation -Left $path -Right $databaseRelative)) {
                throw "$Label overlaps the configured database path; update is blocked."
            }
        }
    }
}

function Assert-HermesStableCurrentTreeSafety {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $DataPaths
    )

    Assert-HermesStableTrackedPathSafety `
        -Context $Context `
        -DataPaths $DataPaths `
        -Paths (Get-HermesStableTrackedPaths -Context $Context) `
        -Label "Current Stable checkout"
}

function Assert-HermesStableTargetTreeSafety {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $Target,
        [Parameter(Mandatory = $true)]
        $DataPaths
    )

    $treeText = Get-HermesStableGitText `
        -Context $Context `
        -ArgumentList @("-C", $Context.RepoRoot, "ls-tree", "-r", "-z", "--name-only", $Target.CommitSha)
    $targetPaths = @(
        Get-HermesStableNullSeparatedItems -Text $treeText |
            ForEach-Object { Get-HermesStableNormalizedGitPath -Path $_ }
    )

    foreach ($targetPath in $targetPaths) {
        if ($targetPath -eq "data/.gitkeep") {
            $gitObject = "{0}:{1}" -f $Target.CommitSha, $targetPath
            $sizeResult = Invoke-HermesStableGit `
                -Context $Context `
                -ArgumentList @("-C", $Context.RepoRoot, "cat-file", "-s", $gitObject)
            $size = 0L
            if (-not [long]::TryParse(([string]$sizeResult.Stdout).Trim(), [ref]$size) -or $size -ne 0) {
                throw "Target release data/.gitkeep is not an empty placeholder; update is blocked."
            }
            continue
        }
        if ($targetPath -eq "data" -or $targetPath.StartsWith("data/", [StringComparison]::Ordinal)) {
            throw "Target release contains a tracked production-data path; update is blocked."
        }
        if (Test-HermesStablePrivateOrRuntimePath -Path $targetPath) {
            throw "Target release contains a tracked runtime/private path; update is blocked."
        }
    }
    if ($targetPaths -notcontains "scripts/prepare-runtime.ps1") {
        throw "Target release does not contain the accepted scripts/prepare-runtime.ps1 contract."
    }

    $databaseRelative = $null
    try {
        $databaseRelative = Get-HermesStableNormalizedGitPath `
            -Path (Get-HermesStableRelativePath -Root $Context.RepoRoot -Path $DataPaths.Database)
    }
    catch {
        $databaseRelative = $null
    }
    if (-not [string]::IsNullOrWhiteSpace($databaseRelative)) {
        foreach ($targetPath in $targetPaths) {
            if ($targetPath -ne "data/.gitkeep" -and (Test-HermesStablePathRelation -Left $targetPath -Right $databaseRelative)) {
                throw "Target release would overwrite the configured Stable database path; update is blocked."
            }
        }
    }
}

function Assert-HermesStableBackupProof {
    param(
        [Parameter(Mandatory = $true)]
        $BackupResult,
        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory
    )

    if ([string]$BackupResult.Stdout -match "^\s*$") {
        throw "Production backup returned no verification proof."
    }
    try {
        $proof = ([string]$BackupResult.Stdout).Trim() | ConvertFrom-Json
    }
    catch {
        throw "Production backup returned invalid verification proof."
    }
    if ($null -eq $proof -or $proof -is [array]) {
        throw "Production backup returned invalid verification proof."
    }
    if ([string]$proof.status -ne "ok") {
        throw "Production backup did not return a successful verification proof."
    }

    $backupId = [string]$proof.backup_id
    $backupName = [string]$proof.backup_name
    if (
        [string]::IsNullOrWhiteSpace($backupId) -or
        [string]::IsNullOrWhiteSpace($backupName) -or
        $backupName -notmatch '^finance_backup_[0-9]{8}T[0-9]{12}Z(?:-[0-9]+)?\.sqlite3$' -or
        [IO.Path]::GetFileName($backupName) -ne $backupName -or
        [IO.Path]::GetFileNameWithoutExtension($backupName) -ne $backupId
    ) {
        throw "Production backup returned an unsafe backup identity."
    }

    $resolvedDirectory = [IO.Path]::GetFullPath($BackupDirectory).TrimEnd("\", "/")
    $backupPath = [IO.Path]::GetFullPath((Join-Path $resolvedDirectory $backupName))
    $parent = Split-Path -Parent $backupPath
    if ($parent -ine $resolvedDirectory) {
        throw "Production backup path escaped the configured backup directory."
    }
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "Production backup file could not be verified in the configured directory."
    }
    Assert-HermesStableNoReparsePath -Path $backupPath -Label "Production backup"
    $backupItem = Get-Item -LiteralPath $backupPath
    if ($backupItem.Length -le 0) {
        throw "Production backup file is empty."
    }
    if ($null -ne $proof.size_bytes) {
        $reportedSize = 0L
        if (-not [long]::TryParse(([string]$proof.size_bytes), [ref]$reportedSize) -or $reportedSize -le 0) {
            throw "Production backup returned an invalid size proof."
        }
    }

    return [pscustomobject]@{
        Id   = $backupId
        Name = $backupName
        Path = $backupPath
    }
}

function Invoke-HermesStableBackup {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [string]$DatabasePath,
        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory
    )

    $scriptPath = Join-Path $ControlCheckout "scripts\launcher-production-backup.py"
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Accepted production backup helper is missing from the control checkout."
    }

    $result = Invoke-HermesStableExternalCommand `
        -Context $Context `
        -Name "python" `
        -FilePath $Context.PythonPath `
        -ArgumentList @(
            $scriptPath,
            "--database", $DatabasePath,
            "--backup-dir", $BackupDirectory
        )
    return Assert-HermesStableBackupProof -BackupResult $result -BackupDirectory $BackupDirectory
}

function Invoke-HermesStableTargetPrepare {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$StableCheckout,
        [Parameter(Mandatory = $true)]
        [ValidateSet("Prepare", "Validate")]
        [string]$Mode
    )

    $scriptPath = Join-Path $StableCheckout "scripts\prepare-runtime.ps1"
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Target checkout does not contain scripts/prepare-runtime.ps1."
    }

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $scriptPath,
        "-Checkout", $StableCheckout,
        "-$Mode"
    )
    return Invoke-HermesStableExternalCommand `
        -Context $Context `
        -Name "powershell.exe" `
        -FilePath $Context.PowerShellPath `
        -ArgumentList $arguments
}

function Assert-HermesStableHead {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha
    )

    $head = (Get-HermesStableGitText `
        -Context $Context `
        -ArgumentList @("-C", $Context.RepoRoot, "rev-parse", "--verify", "HEAD")).Trim().ToLowerInvariant()
    if ($head -ne $ExpectedSha) {
        throw "Stable checkout HEAD is $head, not the proven target commit."
    }
}

function Assert-HermesStableClean {
    param(
        [Parameter(Mandatory = $true)]
        $Context
    )

    $status = Get-HermesStableGitText `
        -Context $Context `
        -ArgumentList @("-C", $Context.RepoRoot, "status", "--porcelain=v1", "--untracked-files=all")
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "Stable checkout is not clean after the update step."
    }
}

function Invoke-HermesStableUpdate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StableCheckout,
        [Parameter(Mandatory = $true)]
        [string]$TargetVersion,
        [string]$DatabasePath,
        [string]$BackupDirectory,
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [scriptblock]$CommandRunner,
        [Parameter(Mandatory = $true)]
        [scriptblock]$CommandResolver,
        [scriptblock]$PortProbe,
        [scriptblock]$ReleaseIdentityValidator
    )

    $targetParts = $null
    $resolvedStable = $null
    $resolvedControl = $null
    $context = $null
    $dataPaths = $null
    $stage = "preflight"
    $target = $null
    $backup = $null
    $switchAttempted = $false
    try {
        # Validate the only owner-selected target before resolving commands or
        # touching any checkout/data state. This rejects branches, SHAs and
        # moving/latest selectors without a fallback path.
        $stage = "target-version-proof"
        $targetParts = Convert-HermesStableVersionParts -Version $TargetVersion -Label "target release"

        $stage = "checkout-path-proof"
        $resolvedStable = Resolve-HermesStableInputPath `
            -Value $StableCheckout `
            -BaseDirectory (Get-Location).Path `
            -Label "Stable checkout"
        $resolvedControl = Resolve-HermesStableInputPath `
            -Value $ControlCheckout `
            -BaseDirectory (Get-Location).Path `
            -Label "Control checkout"
        if (-not (Test-Path -LiteralPath $resolvedStable -PathType Container)) {
            throw "Stable checkout does not exist: $resolvedStable"
        }
        if (-not (Test-Path -LiteralPath $resolvedControl -PathType Container)) {
            throw "Control checkout does not exist: $resolvedControl"
        }
        Assert-HermesStableNoReparsePath -Path $resolvedStable -Label "Stable checkout"
        Assert-HermesStableNoReparsePath -Path $resolvedControl -Label "Control checkout"
        if (Test-HermesStablePathRelation -Left $resolvedStable -Right $resolvedControl) {
            throw "Control checkout must be separate from the explicitly selected Stable checkout."
        }

        $stage = "dependency-proof"
        $gitPath = Get-HermesStableCommandPath `
            -CommandResolver $CommandResolver `
            -Name "git" `
            -InstallHint "Missing dependency 'git'. Install Git for Windows and retry."
        $ghPath = Get-HermesStableCommandPath `
            -CommandResolver $CommandResolver `
            -Name "gh" `
            -InstallHint "Missing dependency 'gh'. Install GitHub CLI and authenticate before updating Stable."
        $pythonPath = Get-HermesStableCommandPath `
            -CommandResolver $CommandResolver `
            -Name "python.exe" `
            -InstallHint "Missing dependency 'python.exe'. Install Python and retry."
        $powerShellPath = Get-HermesStableCommandPath `
            -CommandResolver $CommandResolver `
            -Name "powershell.exe" `
            -InstallHint "Windows PowerShell is required to invoke the target Prepare/Validate contract."

        $context = [pscustomobject]@{
            RepoRoot       = $resolvedStable
            CommandRunner  = $CommandRunner
            GitPath        = $gitPath
            GhPath         = $ghPath
            PythonPath     = $pythonPath
            PowerShellPath = $powerShellPath
            PushUrl        = $null
        }

        $stage = "data-path-proof"
        $dataPaths = Resolve-HermesStableDataPaths `
            -StableCheckout $resolvedStable `
            -DatabasePath $DatabasePath `
            -BackupDirectory $BackupDirectory

        $stage = "origin-proof"
        Assert-HermesStableOrigin -Context $context

        $stage = "current-checkout-proof"
        $checkoutState = Get-HermesStableCheckoutState -Context $context
        $current = Assert-HermesStableCurrentRelease -Context $context -CheckoutState $checkoutState
        Assert-HermesStableCurrentTreeSafety -Context $context -DataPaths $dataPaths

        $stage = "target-release-proof"
        $target = Assert-HermesStableTargetRelease `
            -Context $context `
            -Tag $targetParts.Tag `
            -Version $targetParts
        Assert-HermesStableLocalTargetBeforeBackup -Context $context -Target $target

        $comparison = Compare-HermesStableVersion -Left $target.Version -Right $current.Version
        if ($comparison -lt 0) {
            throw "Target release $($target.Tag) is older than current Stable release $($current.Tag); downgrade is out of scope."
        }
        if ($comparison -eq 0) {
            if ([string]$target.CommitSha -ne [string]$current.CommitSha) {
                throw "Target release $($target.Tag) does not match the current Stable release commit."
            }
            return [pscustomobject]@{
                Status        = "no-op"
                CurrentTag    = $current.Tag
                TargetTag     = $target.Tag
                TargetVersion = $target.Version.Text
                TargetCommit  = $target.CommitSha
                BackupId      = $null
                Prepared      = $false
                Validated     = $false
            }
        }

        $stage = "runtime-gate"
        if ($null -eq $PortProbe) {
            Assert-HermesStablePortFree
        }
        else {
            $portFree = & $PortProbe $resolvedStable
            if (-not [bool]$portFree) {
                throw "Stable runtime is running or port 8000 is occupied; stop it before updating."
            }
        }

        $stage = "verified-backup"
        $backup = Invoke-HermesStableBackup `
            -Context $context `
            -ControlCheckout $resolvedControl `
            -DatabasePath $dataPaths.Database `
            -BackupDirectory $dataPaths.Backup

        $stage = "target-fetch"
        $targetRef = "refs/tags/{0}" -f $target.Tag
        $targetRefspec = "{0}:{0}" -f $targetRef
        $fetch = Invoke-HermesStableGit `
            -Context $context `
            -ArgumentList @(
                "-C", $resolvedStable,
                "fetch", "--no-tags", "origin", $targetRefspec
            )

        $stage = "fetched-target-proof"
        Assert-HermesStableFetchedTarget -Context $context -Target $target
        Assert-HermesStableTargetCodeIdentity -Context $context -Target $target
        Assert-HermesStableTargetTreeSafety -Context $context -Target $target -DataPaths $dataPaths

        $stage = "checkout-switch"
        $switchAttempted = $true
        $switch = Invoke-HermesStableGit `
            -Context $context `
            -ArgumentList @("-C", $resolvedStable, "switch", "--detach", "--no-overwrite-ignore", $target.CommitSha)

        $stage = "post-switch-proof"
        Assert-HermesStableHead -Context $context -ExpectedSha $target.CommitSha
        Assert-HermesStableClean -Context $context
        if ($null -eq $ReleaseIdentityValidator) {
            Assert-HermesReleaseIdentity -RepoRoot $resolvedStable -Version $target.Version.Text | Out-Null
        }
        else {
            & $ReleaseIdentityValidator $resolvedStable $target.Version.Text
        }

        $stage = "target-prepare"
        $prepare = Invoke-HermesStableTargetPrepare `
            -Context $context `
            -StableCheckout $resolvedStable `
            -Mode "Prepare"

        $stage = "target-validate"
        $validate = Invoke-HermesStableTargetPrepare `
            -Context $context `
            -StableCheckout $resolvedStable `
            -Mode "Validate"

        $stage = "final-verify"
        Assert-HermesStableHead -Context $context -ExpectedSha $target.CommitSha
        Assert-HermesStableClean -Context $context
        if ($null -eq $ReleaseIdentityValidator) {
            Assert-HermesReleaseIdentity -RepoRoot $resolvedStable -Version $target.Version.Text | Out-Null
        }
        else {
            & $ReleaseIdentityValidator $resolvedStable $target.Version.Text
        }

        return [pscustomobject]@{
            Status        = "updated"
            CurrentTag    = $current.Tag
            TargetTag     = $target.Tag
            TargetVersion = $target.Version.Text
            TargetCommit  = $target.CommitSha
            BackupId      = $backup.Id
            Prepared      = $true
            Validated     = $true
        }
    }
    catch {
        $detail = [string]$_.Exception.Message
        $observedHead = $null
        if ($switchAttempted) {
            try {
                $observedHead = (Get-HermesStableGitText `
                    -Context $context `
                    -ArgumentList @("-C", $resolvedStable, "rev-parse", "--verify", "HEAD")).Trim().ToLowerInvariant()
            }
            catch {
                $observedHead = $null
            }
        }

        if ($switchAttempted -and $null -ne $target -and $observedHead -eq [string]$target.CommitSha) {
            throw "Stable update failed at stage '$stage'; status=target-pinned-but-unprepared; target_tag=$($target.Tag); target_commit=$($target.CommitSha); rollback=not-attempted; auto-start=not-attempted; db-migration=not-attempted. $detail"
        }
        if ($switchAttempted) {
            throw "Stable update failed at stage '$stage'; status=checkout-switch-not-proven; rollback=not-attempted; auto-start=not-attempted; db-migration=not-attempted. $detail"
        }
        if ($null -ne $backup) {
            throw "Stable update failed at stage '$stage'; status=backup-verified-checkout-not-switched; backup_id=$($backup.Id); auto-start=not-attempted; db-migration=not-attempted. $detail"
        }
        throw "Stable update failed at stage '$stage'; status=stable-checkout-unchanged; auto-start=not-attempted; db-migration=not-attempted. $detail"
    }
}
