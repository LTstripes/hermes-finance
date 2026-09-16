# Composable exact-candidate Preview/UAT preparation for Hermes Finance.
# The public entrypoint is scripts/prepare-preview.ps1.  This helper keeps
# candidate proof, clone/data-boundary checks, and target Prepare/Validate
# invocations testable without making the launcher or a mutable main branch
# the owner of the operation.

Set-StrictMode -Version 2.0
$script:HermesPreviewFileIdentityLoaded = $false

function Resolve-HermesPreviewInputPath {
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

function Get-HermesPreviewPathKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return ([IO.Path]::GetFullPath($Path)).TrimEnd("\", "/").ToLowerInvariant()
}

function Test-HermesPreviewSamePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Left,
        [Parameter(Mandatory = $true)]
        [string]$Right
    )

    return (Get-HermesPreviewPathKey -Path $Left) -eq (Get-HermesPreviewPathKey -Path $Right)
}

function Test-HermesPreviewPathRelation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Left,
        [Parameter(Mandatory = $true)]
        [string]$Right
    )

    $leftKey = Get-HermesPreviewPathKey -Path $Left
    $rightKey = Get-HermesPreviewPathKey -Path $Right
    return (
        $leftKey -eq $rightKey -or
        $leftKey.StartsWith($rightKey + "\", [StringComparison]::OrdinalIgnoreCase) -or
        $rightKey.StartsWith($leftKey + "\", [StringComparison]::OrdinalIgnoreCase)
    )
}

function Test-HermesPreviewIsWithin {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Child,
        [Parameter(Mandatory = $true)]
        [string]$Parent
    )

    $childKey = Get-HermesPreviewPathKey -Path $Child
    $parentKey = Get-HermesPreviewPathKey -Path $Parent
    return (
        $childKey -eq $parentKey -or
        $childKey.StartsWith($parentKey + "\", [StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-HermesPreviewNoReparsePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label uses a symlink, junction, or reparse point; Preview preparation is blocked."
            }
        }

        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -ieq $current) {
            break
        }
        $current = $parent
    }
}

function Assert-HermesPreviewExistingDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label does not exist."
    }
    Assert-HermesPreviewNoReparsePath -Path $Path -Label $Label
}

function Assert-HermesPreviewExistingFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label does not exist as a regular file."
    }
    Assert-HermesPreviewNoReparsePath -Path $Path -Label $Label
}

function New-HermesPreviewCommandResolver {
    return {
        param(
            [Parameter(Mandatory = $true)]
            [string]$Name
        )

        $command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            return $null
        }
        return $command.Source
    }.GetNewClosure()
}

function Invoke-HermesPreviewNativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        $Request
    )

    $oldPrompt = [Environment]::GetEnvironmentVariable("GIT_TERMINAL_PROMPT", "Process")
    $oldErrorActionPreference = $ErrorActionPreference
    $exitCode = 1
    $output = ""
    try {
        $ErrorActionPreference = "Continue"
        if ([string]$Request.Name -eq "git") {
            [Environment]::SetEnvironmentVariable("GIT_TERMINAL_PROMPT", "0", "Process")
        }

        Push-Location $Request.WorkingDirectory
        try {
            $output = & $Request.FilePath @($Request.Arguments) 2>&1 | Out-String
            $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        }
        finally {
            Pop-Location
        }
    }
    catch {
        $output = [string]$_.Exception.Message
        $exitCode = 1
    }
    finally {
        [Environment]::SetEnvironmentVariable("GIT_TERMINAL_PROMPT", $oldPrompt, "Process")
        $ErrorActionPreference = $oldErrorActionPreference
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Stdout   = $output
        Stderr   = ""
    }
}

function New-HermesPreviewCommandRunner {
    return {
        param(
            [Parameter(Mandatory = $true)]
            $Request
        )

        return Invoke-HermesPreviewNativeCommand -Request $Request
    }.GetNewClosure()
}

function Get-HermesPreviewRequiredCommand {
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

function Invoke-HermesPreviewExternalCommand {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @(),
        [switch]$AllowFailure
    )

    $request = [pscustomobject]@{
        Name             = $Name
        FileName         = $FilePath
        FilePath         = $FilePath
        WorkingDirectory = $WorkingDirectory
        Arguments        = @($ArgumentList)
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

function Invoke-HermesPreviewGit {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @(),
        [switch]$AllowFailure
    )

    return Invoke-HermesPreviewExternalCommand `
        -Context $Context `
        -Name "git" `
        -FilePath $Context.GitPath `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList $ArgumentList `
        -AllowFailure:$AllowFailure
}

function Get-HermesPreviewGitText {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [AllowEmptyCollection()]
        [string[]]$ArgumentList = @()
    )

    $result = Invoke-HermesPreviewGit `
        -Context $Context `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList $ArgumentList
    return ([string]$result.Stdout).Trim()
}

function Get-HermesPreviewGitCommonDirectory {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Checkout
    )

    $raw = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("rev-parse", "--git-common-dir")
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "Git common directory cannot be proven for $Checkout."
    }
    $resolved = if ([IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $Checkout $raw }
    $resolved = [IO.Path]::GetFullPath($resolved)
    Assert-HermesPreviewExistingDirectory -Path $resolved -Label "Git common directory"
    return $resolved
}

function Get-HermesPreviewGitDirectory {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Checkout
    )

    $raw = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("rev-parse", "--git-dir")
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "Git directory cannot be proven for $Checkout."
    }
    $resolved = if ([IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $Checkout $raw }
    return [IO.Path]::GetFullPath($resolved)
}

function Get-HermesPreviewGitSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Assert-HermesPreviewExistingDirectory -Path $Checkout -Label $Label
    $topLevel = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("rev-parse", "--show-toplevel")
    if (-not (Test-HermesPreviewSamePath -Left $topLevel -Right $Checkout)) {
        throw "$Label is not the selected Git checkout."
    }
    $head = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("rev-parse", "--verify", "HEAD")
    if ($head -notmatch "^[0-9a-fA-F]{40}$") {
        throw "$Label HEAD is not a full commit SHA."
    }
    $status = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
    return [pscustomobject]@{
        Checkout = [IO.Path]::GetFullPath($Checkout)
        Head     = $head.ToLowerInvariant()
        Status   = $status
        Common   = Get-HermesPreviewGitCommonDirectory -Context $Context -Checkout $Checkout
    }
}

function Assert-HermesPreviewGitSnapshotUnchanged {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        $Snapshot,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $current = Get-HermesPreviewGitSnapshot -Context $Context -Checkout $Snapshot.Checkout -Label $Label
    if ($current.Head -ne $Snapshot.Head -or $current.Status -ne $Snapshot.Status -or
        -not (Test-HermesPreviewSamePath -Left $current.Common -Right $Snapshot.Common)) {
        throw "$Label changed during Preview preparation."
    }
}

function Assert-HermesPreviewCleanCheckout {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $status = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
    $conflicts = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("ls-files", "-u")
    if (-not [string]::IsNullOrWhiteSpace($status) -or -not [string]::IsNullOrWhiteSpace($conflicts)) {
        throw "$Label has uncommitted or conflicted changes."
    }
}

function Get-HermesPreviewRemoteKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $candidate = $Value.Trim().TrimEnd("/", "\")
    if ($candidate -match '^git@([^:]+):(.+)$') {
        $candidate = "$($Matches[1])/$($Matches[2])"
    }
    elseif ($candidate -match '^(?:https?|ssh)://([^/]+)/(.+)$') {
        $candidate = "$($Matches[1])/$($Matches[2])"
    }
    elseif ($candidate -match '^file://') {
        try {
            $candidate = [IO.Path]::GetFullPath(([Uri]$candidate).LocalPath)
        }
        catch {
            throw "Repository remote is not a valid file URL."
        }
    }
    elseif ([IO.Path]::IsPathRooted($candidate)) {
        $candidate = [IO.Path]::GetFullPath($candidate)
    }

    if ($candidate.EndsWith(".git", [StringComparison]::OrdinalIgnoreCase)) {
        $candidate = $candidate.Substring(0, $candidate.Length - 4)
    }
    return $candidate.TrimEnd("/", "\").ToLowerInvariant()
}

function Assert-HermesPreviewRepositoryIdentity {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Checkout,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedRemote,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $remote = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("remote", "get-url", "origin")
    if ([string]::IsNullOrWhiteSpace($remote) -or
        (Get-HermesPreviewRemoteKey -Value $remote) -ne (Get-HermesPreviewRemoteKey -Value $ExpectedRemote)) {
        throw "$Label origin is not the expected Hermes Finance repository."
    }
}

function Assert-HermesPreviewCandidateSha {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CandidateSha
    )

    $normalized = $CandidateSha.Trim().ToLowerInvariant()
    if ($normalized -notmatch "^[0-9a-f]{40}$") {
        throw "Candidate SHA must be one explicit full 40-hex commit SHA; branches, latest, and abbreviated values are rejected."
    }
    return $normalized
}

function Assert-HermesPreviewCandidateProvenance {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [string]$CandidateSha
    )

    $candidateType = Get-HermesPreviewGitText `
        -Context $Context `
        -WorkingDirectory $ControlCheckout `
        -ArgumentList @("cat-file", "-t", $CandidateSha)
    if ($candidateType -ne "commit") {
        throw "Candidate SHA is not a commit in the selected repository."
    }

    $resolved = Get-HermesPreviewGitText `
        -Context $Context `
        -WorkingDirectory $ControlCheckout `
        -ArgumentList @("rev-parse", "--verify", ("{0}^{{commit}}" -f $CandidateSha))
    if ($resolved.ToLowerInvariant() -ne $CandidateSha) {
        throw "Candidate SHA did not resolve to itself as a commit."
    }

    $remoteText = [string](Invoke-HermesPreviewGit `
            -Context $Context `
            -WorkingDirectory $ControlCheckout `
            -ArgumentList @("ls-remote", "--heads", "--tags", "origin")).Stdout
    $remoteMatch = $false
    foreach ($line in ($remoteText -split "\r?\n")) {
        $parts = @($line.Trim() -split "\s+")
        if ($parts.Count -ge 1 -and $parts[0].ToLowerInvariant() -eq $CandidateSha) {
            $remoteMatch = $true
            break
        }
    }

    if (-not $remoteMatch) {
        $refs = @(
            Get-HermesPreviewGitText `
                -Context $Context `
                -WorkingDirectory $ControlCheckout `
                -ArgumentList @("for-each-ref", "--format=%(refname)", "refs/remotes/origin", "refs/heads") |
                ForEach-Object { $_ -split "\r?\n" } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        foreach ($ref in $refs) {
            $ancestor = Invoke-HermesPreviewGit `
                -Context $Context `
                -WorkingDirectory $ControlCheckout `
                -ArgumentList @("merge-base", "--is-ancestor", $CandidateSha, [string]$ref) `
                -AllowFailure
            if ([int]$ancestor.ExitCode -eq 0) {
                $remoteMatch = $true
                break
            }
        }
    }

    if (-not $remoteMatch) {
        throw "Candidate SHA is not proven by the selected repository origin."
    }
}

function Test-HermesPreviewForbiddenTrackedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $normalized = $Path.Trim().Replace("\", "/").TrimStart("./").ToLowerInvariant()
    if ($normalized -eq ".env" -or
        ($normalized.StartsWith(".env.", [StringComparison]::Ordinal) -and $normalized -ne ".env.example") -or
        $normalized -eq "private" -or $normalized.StartsWith("private/", [StringComparison]::Ordinal) -or
        $normalized -eq "backups" -or $normalized.StartsWith("backups/", [StringComparison]::Ordinal) -or
        $normalized -eq "backend/.venv" -or $normalized.StartsWith("backend/.venv/", [StringComparison]::Ordinal) -or
        $normalized -eq "frontend/node_modules" -or $normalized.StartsWith("frontend/node_modules/", [StringComparison]::Ordinal) -or
        $normalized -eq "frontend/dist" -or $normalized.StartsWith("frontend/dist/", [StringComparison]::Ordinal) -or
        $normalized -eq ".hermes-runtime-prepared.json" -or
        $normalized -eq ".hermes-data-identity.json") {
        return $true
    }
    if ($normalized -eq "data" -or $normalized.StartsWith("data/", [StringComparison]::Ordinal)) {
        return $normalized -ne "data/.gitkeep"
    }
    return $false
}

function Assert-HermesPreviewCandidateTree {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [string]$CandidateSha
    )

    $prepareObject = "{0}:scripts/prepare-runtime.ps1" -f $CandidateSha
    $prepareProof = Invoke-HermesPreviewGit `
        -Context $Context `
        -WorkingDirectory $ControlCheckout `
        -ArgumentList @("cat-file", "-e", $prepareObject) `
        -AllowFailure
    if ([int]$prepareProof.ExitCode -ne 0) {
        throw "Candidate checkout does not contain the accepted scripts/prepare-runtime.ps1 contract."
    }

    $treeText = Get-HermesPreviewGitText `
        -Context $Context `
        -WorkingDirectory $ControlCheckout `
        -ArgumentList @("ls-tree", "-r", "--name-only", $CandidateSha)
    foreach ($path in ($treeText -split "\r?\n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        if (Test-HermesPreviewForbiddenTrackedPath -Path ([string]$path)) {
            throw "Candidate checkout contains a tracked private or runtime path; Preview preparation is blocked."
        }
    }
}

function Add-HermesPreviewFileIdentityType {
    if ($script:HermesPreviewFileIdentityLoaded) {
        return
    }

    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class HermesPreviewNativeMethods
{
    [StructLayout(LayoutKind.Sequential)]
    public struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out ByHandleFileInformation fileInformation);
}
'@
    $script:HermesPreviewFileIdentityLoaded = $true
}

function Get-HermesPreviewFileIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw "$Label file identity cannot be proven outside Windows."
    }
    Add-HermesPreviewFileIdentityType
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
    try {
        $info = New-Object HermesPreviewNativeMethods+ByHandleFileInformation
        if (-not [HermesPreviewNativeMethods]::GetFileInformationByHandle($stream.SafeFileHandle, [ref]$info)) {
            throw "$Label file identity could not be read."
        }
        return "{0:x8}:{1:x8}:{2:x8}" -f $info.VolumeSerialNumber, $info.FileIndexHigh, $info.FileIndexLow
    }
    finally {
        $stream.Dispose()
    }
}

function Assert-HermesPreviewDataSidecar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDirectory,
        [Parameter(Mandatory = $true)]
        [string]$Database
    )

    $sidecar = Join-Path $DataDirectory ".hermes-data-identity.json"
    if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
        if (Test-Path -LiteralPath $Database -PathType Leaf) {
            throw "Existing Preview/UAT database requires a kind=preview sidecar."
        }
        return $sidecar
    }
    Assert-HermesPreviewNoReparsePath -Path $sidecar -Label "Preview/UAT data sidecar"
    try {
        $document = Get-Content -LiteralPath $sidecar -Raw | ConvertFrom-Json
    }
    catch {
        throw "Preview/UAT data sidecar is invalid."
    }
    if ($null -eq $document -or $document -is [array] -or [string]$document.kind -cne "preview") {
        throw "Preview/UAT data sidecar must declare kind=preview."
    }
    return $sidecar
}

function Assert-HermesPreviewDataBoundary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [string]$StableCheckout,
        [Parameter(Mandatory = $true)]
        [string]$StableDataDirectory,
        [Parameter(Mandatory = $true)]
        [string]$StableDatabase,
        [Parameter(Mandatory = $true)]
        [string]$PreviewCheckout,
        [Parameter(Mandatory = $true)]
        [string]$PreviewDataDirectory,
        [Parameter(Mandatory = $true)]
        [string]$PreviewDatabase
    )

    Assert-HermesPreviewExistingDirectory -Path $StableCheckout -Label "Stable checkout"
    Assert-HermesPreviewExistingDirectory -Path $StableDataDirectory -Label "Stable data directory"
    Assert-HermesPreviewExistingFile -Path $StableDatabase -Label "Stable database"
    if (-not (Test-HermesPreviewIsWithin -Child $StableDatabase -Parent $StableDataDirectory)) {
        throw "Stable database must be inside Stable data directory."
    }

    Assert-HermesPreviewNoReparsePath -Path $ControlCheckout -Label "Control checkout"
    Assert-HermesPreviewNoReparsePath -Path $PreviewCheckout -Label "Preview checkout"
    Assert-HermesPreviewNoReparsePath -Path $PreviewDataDirectory -Label "Preview data directory"
    Assert-HermesPreviewNoReparsePath -Path $PreviewDatabase -Label "Preview database"

    if (-not (Test-HermesPreviewIsWithin -Child $PreviewDatabase -Parent $PreviewDataDirectory)) {
        throw "Preview database must be inside the Preview data directory."
    }

    foreach ($candidate in @(
        [pscustomobject]@{ Path = $PreviewCheckout; Label = "Preview checkout" },
        [pscustomobject]@{ Path = $PreviewDataDirectory; Label = "Preview data directory" },
        [pscustomobject]@{ Path = $PreviewDatabase; Label = "Preview database" }
    )) {
        foreach ($forbidden in @(
            [pscustomobject]@{ Path = $ControlCheckout; Label = "control checkout" },
            [pscustomobject]@{ Path = $StableCheckout; Label = "Stable checkout" },
            [pscustomobject]@{ Path = $StableDataDirectory; Label = "Stable data directory" },
            [pscustomobject]@{ Path = $StableDatabase; Label = "Stable database" }
        )) {
            if (Test-HermesPreviewPathRelation -Left $candidate.Path -Right $forbidden.Path) {
                throw "$($candidate.Label) aliases or overlaps the $($forbidden.Label)."
            }
        }
    }

    if ((Test-Path -LiteralPath $PreviewDatabase -PathType Leaf) -and
        (Get-HermesPreviewFileIdentity -Path $PreviewDatabase -Label "Preview database") -eq
        (Get-HermesPreviewFileIdentity -Path $StableDatabase -Label "Stable database")) {
        throw "Preview database aliases the Stable database by file identity."
    }

    return Assert-HermesPreviewDataSidecar -DataDirectory $PreviewDataDirectory -Database $PreviewDatabase
}

function Assert-HermesPreviewIndependentCheckout {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$PreviewCheckout,
        [Parameter(Mandatory = $true)]
        [string]$ControlCommonDirectory,
        [Parameter(Mandatory = $true)]
        [string]$StableCommonDirectory
    )

    Assert-HermesPreviewExistingDirectory -Path $PreviewCheckout -Label "Preview checkout"
    $dotGit = Join-Path $PreviewCheckout ".git"
    if (-not (Test-Path -LiteralPath $dotGit -PathType Container)) {
        throw "Preview/UAT must be an independent Git clone with its own .git directory, not a linked worktree."
    }
    Assert-HermesPreviewNoReparsePath -Path $dotGit -Label "Preview Git directory"
    $topLevel = Get-HermesPreviewGitText -Context $Context -WorkingDirectory $PreviewCheckout -ArgumentList @("rev-parse", "--show-toplevel")
    if (-not (Test-HermesPreviewSamePath -Left $topLevel -Right $PreviewCheckout)) {
        throw "Preview checkout Git toplevel does not match the selected checkout."
    }
    $common = Get-HermesPreviewGitCommonDirectory -Context $Context -Checkout $PreviewCheckout
    $gitDirectory = Get-HermesPreviewGitDirectory -Context $Context -Checkout $PreviewCheckout
    if (-not (Test-HermesPreviewSamePath -Left $common -Right $gitDirectory)) {
        throw "Preview/UAT is a linked worktree; its Git common directory is not its own Git directory."
    }
    if ((Test-HermesPreviewSamePath -Left $common -Right $ControlCommonDirectory) -or
        (Test-HermesPreviewSamePath -Left $common -Right $StableCommonDirectory)) {
        throw "Preview/UAT Git metadata is shared with the control or Stable checkout."
    }
    return $common
}

function Assert-HermesPreviewStableAndControlSeparation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [string]$StableCheckout
    )

    if (Test-HermesPreviewPathRelation -Left $ControlCheckout -Right $StableCheckout) {
        throw "Control and Stable checkouts must be separate paths."
    }
}

function Invoke-HermesPreviewTargetRuntimeStep {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$PreviewCheckout,
        [Parameter(Mandatory = $true)]
        [ValidateSet("Prepare", "Validate")]
        [string]$Mode
    )

    $scriptPath = Join-Path $PreviewCheckout "scripts\prepare-runtime.ps1"
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Target checkout does not contain scripts/prepare-runtime.ps1."
    }
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $scriptPath,
        "-Checkout", $PreviewCheckout,
        "-$Mode"
    )
    return Invoke-HermesPreviewExternalCommand `
        -Context $Context `
        -Name "powershell.exe" `
        -FilePath $Context.PowerShellPath `
        -WorkingDirectory $PreviewCheckout `
        -ArgumentList $arguments
}

function Write-HermesPreviewSidecarIfMissing {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDirectory,
        [Parameter(Mandatory = $true)]
        [string]$SidecarPath
    )

    if (Test-Path -LiteralPath $SidecarPath -PathType Leaf) {
        return
    }
    if (-not (Test-Path -LiteralPath $DataDirectory -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
    }
    Assert-HermesPreviewNoReparsePath -Path $DataDirectory -Label "Preview data directory"
    $temporary = "$SidecarPath.tmp.$([guid]::NewGuid().ToString('N'))"
    $document = [ordered]@{
        kind       = "preview"
        profile_id = "preview"
        updated_at = [DateTimeOffset]::UtcNow.ToString("O")
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($temporary, (($document | ConvertTo-Json -Compress) + [Environment]::NewLine), $encoding)
        Move-Item -LiteralPath $temporary -Destination $SidecarPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
    Assert-HermesPreviewNoReparsePath -Path $SidecarPath -Label "Preview/UAT data sidecar"
}

function Get-HermesPreviewObservedHead {
    param(
        [Parameter(Mandatory = $true)]
        $Context,
        [Parameter(Mandatory = $true)]
        [string]$Checkout
    )

    try {
        return (Get-HermesPreviewGitText -Context $Context -WorkingDirectory $Checkout -ArgumentList @("rev-parse", "--verify", "HEAD")).ToLowerInvariant()
    }
    catch {
        return $null
    }
}

function Invoke-HermesPreviewPreparation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CandidateSha,
        [Parameter(Mandatory = $true)]
        [string]$ControlCheckout,
        [Parameter(Mandatory = $true)]
        [string]$PreviewCheckout,
        [Parameter(Mandatory = $true)]
        [string]$PreviewDataDirectory,
        [Parameter(Mandatory = $true)]
        [string]$PreviewDatabase,
        [Parameter(Mandatory = $true)]
        [string]$StableCheckout,
        [Parameter(Mandatory = $true)]
        [string]$StableDataDirectory,
        [Parameter(Mandatory = $true)]
        [string]$StableDatabase,
        [string]$RepositoryUrl = "https://github.com/LTstripes/hermes-finance.git",
        [Parameter(Mandatory = $true)]
        [scriptblock]$CommandRunner,
        [Parameter(Mandatory = $true)]
        [scriptblock]$CommandResolver
    )

    $context = $null
    $stage = "preflight"
    $resolvedCandidate = $null
    $resolvedControl = $null
    $resolvedPreview = $null
    $resolvedPreviewData = $null
    $resolvedPreviewDatabase = $null
    $resolvedStable = $null
    $resolvedStableData = $null
    $resolvedStableDatabase = $null
    $controlSnapshot = $null
    $stableSnapshot = $null
    $targetExisted = $false
    try {
        $resolvedCandidate = Assert-HermesPreviewCandidateSha -CandidateSha $CandidateSha
        $baseDirectory = (Get-Location).Path
        $resolvedControl = Resolve-HermesPreviewInputPath -Value $ControlCheckout -BaseDirectory $baseDirectory -Label "Control checkout"
        $resolvedPreview = Resolve-HermesPreviewInputPath -Value $PreviewCheckout -BaseDirectory $baseDirectory -Label "Preview checkout"
        $resolvedPreviewData = Resolve-HermesPreviewInputPath -Value $PreviewDataDirectory -BaseDirectory $baseDirectory -Label "Preview data directory"
        $resolvedPreviewDatabase = Resolve-HermesPreviewInputPath -Value $PreviewDatabase -BaseDirectory $baseDirectory -Label "Preview database"
        $resolvedStable = Resolve-HermesPreviewInputPath -Value $StableCheckout -BaseDirectory $baseDirectory -Label "Stable checkout"
        $resolvedStableData = Resolve-HermesPreviewInputPath -Value $StableDataDirectory -BaseDirectory $baseDirectory -Label "Stable data directory"
        $resolvedStableDatabase = Resolve-HermesPreviewInputPath -Value $StableDatabase -BaseDirectory $baseDirectory -Label "Stable database"

        if ((Test-HermesPreviewPathRelation -Left $resolvedPreview -Right $resolvedControl) -or
            (Test-HermesPreviewPathRelation -Left $resolvedPreview -Right $resolvedStable)) {
            throw "Preview checkout must be separate from the control and Stable checkout."
        }
        Assert-HermesPreviewStableAndControlSeparation -ControlCheckout $resolvedControl -StableCheckout $resolvedStable

        $gitPath = Get-HermesPreviewRequiredCommand `
            -CommandResolver $CommandResolver `
            -Name "git.exe" `
            -InstallHint "Missing dependency 'git.exe'. Install Git for Windows and retry."
        $powerShellPath = Get-HermesPreviewRequiredCommand `
            -CommandResolver $CommandResolver `
            -Name "powershell.exe" `
            -InstallHint "Windows PowerShell is required to invoke target Prepare/Validate."
        $context = [pscustomobject]@{
            CommandRunner  = $CommandRunner
            GitPath        = $gitPath
            PowerShellPath = $powerShellPath
        }

        $stage = "control-proof"
        $controlSnapshot = Get-HermesPreviewGitSnapshot `
            -Context $context `
            -Checkout $resolvedControl `
            -Label "Control checkout"
        Assert-HermesPreviewRepositoryIdentity `
            -Context $context `
            -Checkout $resolvedControl `
            -ExpectedRemote $RepositoryUrl `
            -Label "Control checkout"
        Assert-HermesPreviewCandidateProvenance `
            -Context $context `
            -ControlCheckout $resolvedControl `
            -CandidateSha $resolvedCandidate
        Assert-HermesPreviewCandidateTree `
            -Context $context `
            -ControlCheckout $resolvedControl `
            -CandidateSha $resolvedCandidate

        $stage = "stable-proof"
        $stableSnapshot = Get-HermesPreviewGitSnapshot `
            -Context $context `
            -Checkout $resolvedStable `
            -Label "Stable checkout"
        Assert-HermesPreviewDataBoundary `
            -ControlCheckout $resolvedControl `
            -StableCheckout $resolvedStable `
            -StableDataDirectory $resolvedStableData `
            -StableDatabase $resolvedStableDatabase `
            -PreviewCheckout $resolvedPreview `
            -PreviewDataDirectory $resolvedPreviewData `
            -PreviewDatabase $resolvedPreviewDatabase | Out-Null

        $controlCommon = $controlSnapshot.Common
        $stableCommon = $stableSnapshot.Common
        $targetExisted = Test-Path -LiteralPath $resolvedPreview
        if ($targetExisted -and -not (Test-Path -LiteralPath $resolvedPreview -PathType Container)) {
            throw "Preview checkout path exists but is not a directory."
        }
        if (-not $targetExisted) {
            $targetParent = Split-Path -Parent $resolvedPreview
            Assert-HermesPreviewExistingDirectory -Path $targetParent -Label "Preview checkout parent"
        }

        if ($targetExisted) {
            $stage = "preview-identity-proof"
            Assert-HermesPreviewIndependentCheckout `
                -Context $context `
                -PreviewCheckout $resolvedPreview `
                -ControlCommonDirectory $controlCommon `
                -StableCommonDirectory $stableCommon | Out-Null
            Assert-HermesPreviewRepositoryIdentity `
                -Context $context `
                -Checkout $resolvedPreview `
                -ExpectedRemote $RepositoryUrl `
                -Label "Preview checkout"
            Assert-HermesPreviewCleanCheckout `
                -Context $context `
                -Checkout $resolvedPreview `
                -Label "Preview checkout"
        }

        $stage = "checkout-pin"
        if (-not $targetExisted) {
            $clone = Invoke-HermesPreviewGit `
                -Context $context `
                -WorkingDirectory (Split-Path -Parent $resolvedPreview) `
                -ArgumentList @("clone", "--no-local", "--no-checkout", $resolvedControl, $resolvedPreview)
            Invoke-HermesPreviewGit `
                -Context $context `
                -WorkingDirectory $resolvedPreview `
                -ArgumentList @("remote", "set-url", "origin", $RepositoryUrl) | Out-Null
        }

        Assert-HermesPreviewNoReparsePath -Path $resolvedPreview -Label "Preview checkout"
        Assert-HermesPreviewIndependentCheckout `
            -Context $context `
            -PreviewCheckout $resolvedPreview `
            -ControlCommonDirectory $controlCommon `
            -StableCommonDirectory $stableCommon | Out-Null
        Assert-HermesPreviewRepositoryIdentity `
            -Context $context `
            -Checkout $resolvedPreview `
            -ExpectedRemote $RepositoryUrl `
            -Label "Preview checkout"

        $candidateInTarget = Invoke-HermesPreviewGit `
            -Context $context `
            -WorkingDirectory $resolvedPreview `
            -ArgumentList @("cat-file", "-e", ("{0}^{{commit}}" -f $resolvedCandidate)) `
            -AllowFailure
        if ([int]$candidateInTarget.ExitCode -ne 0) {
            Invoke-HermesPreviewGit `
                -Context $context `
                -WorkingDirectory $resolvedPreview `
                -ArgumentList @("fetch", "--no-tags", "--no-prune", "origin", $resolvedCandidate) | Out-Null
        }
        Invoke-HermesPreviewGit `
            -Context $context `
            -WorkingDirectory $resolvedPreview `
            -ArgumentList @("switch", "--detach", "--no-overwrite-ignore", $resolvedCandidate) | Out-Null
        Assert-HermesPreviewCleanCheckout `
            -Context $context `
            -Checkout $resolvedPreview `
            -Label "Preview checkout"
        $pinnedHead = Get-HermesPreviewGitText -Context $context -WorkingDirectory $resolvedPreview -ArgumentList @("rev-parse", "--verify", "HEAD")
        if ($pinnedHead.ToLowerInvariant() -ne $resolvedCandidate) {
            throw "Preview checkout did not resolve exactly to the requested candidate SHA."
        }

        $stage = "prepare"
        Invoke-HermesPreviewTargetRuntimeStep `
            -Context $context `
            -PreviewCheckout $resolvedPreview `
            -Mode "Prepare" | Out-Null
        $afterPrepare = Get-HermesPreviewGitText -Context $context -WorkingDirectory $resolvedPreview -ArgumentList @("rev-parse", "--verify", "HEAD")
        if ($afterPrepare.ToLowerInvariant() -ne $resolvedCandidate) {
            throw "Target Prepare changed the pinned Preview candidate."
        }

        $stage = "validate"
        Invoke-HermesPreviewTargetRuntimeStep `
            -Context $context `
            -PreviewCheckout $resolvedPreview `
            -Mode "Validate" | Out-Null
        $afterValidate = Get-HermesPreviewGitText -Context $context -WorkingDirectory $resolvedPreview -ArgumentList @("rev-parse", "--verify", "HEAD")
        if ($afterValidate.ToLowerInvariant() -ne $resolvedCandidate) {
            throw "Target Validate changed the pinned Preview candidate."
        }

        $stage = "data-attach"
        Assert-HermesPreviewDataBoundary `
            -ControlCheckout $resolvedControl `
            -StableCheckout $resolvedStable `
            -StableDataDirectory $resolvedStableData `
            -StableDatabase $resolvedStableDatabase `
            -PreviewCheckout $resolvedPreview `
            -PreviewDataDirectory $resolvedPreviewData `
            -PreviewDatabase $resolvedPreviewDatabase | Out-Null
        $sidecarPath = Join-Path $resolvedPreviewData ".hermes-data-identity.json"
        Write-HermesPreviewSidecarIfMissing -DataDirectory $resolvedPreviewData -SidecarPath $sidecarPath

        $stage = "final-proof"
        Assert-HermesPreviewIndependentCheckout `
            -Context $context `
            -PreviewCheckout $resolvedPreview `
            -ControlCommonDirectory $controlCommon `
            -StableCommonDirectory $stableCommon | Out-Null
        Assert-HermesPreviewRepositoryIdentity `
            -Context $context `
            -Checkout $resolvedPreview `
            -ExpectedRemote $RepositoryUrl `
            -Label "Preview checkout"
        Assert-HermesPreviewCleanCheckout `
            -Context $context `
            -Checkout $resolvedPreview `
            -Label "Preview checkout"
        $finalHead = Get-HermesPreviewGitText -Context $context -WorkingDirectory $resolvedPreview -ArgumentList @("rev-parse", "--verify", "HEAD")
        if ($finalHead.ToLowerInvariant() -ne $resolvedCandidate) {
            throw "Final Preview pin proof did not match the requested candidate SHA."
        }
        Assert-HermesPreviewDataSidecar -DataDirectory $resolvedPreviewData -Database $resolvedPreviewDatabase | Out-Null
        Assert-HermesPreviewGitSnapshotUnchanged -Context $context -Snapshot $controlSnapshot -Label "Control checkout"
        Assert-HermesPreviewGitSnapshotUnchanged -Context $context -Snapshot $stableSnapshot -Label "Stable checkout"

        return [pscustomobject]@{
            Status          = "prepared"
            CandidateSha    = $resolvedCandidate
            PreviewCheckout = $resolvedPreview
            PreviewDataDir  = $resolvedPreviewData
            PreviewDatabase = $resolvedPreviewDatabase
            Prepared        = $true
            Validated       = $true
            Started         = $false
            Migrated        = $false
            SidecarKind     = "preview"
        }
    }
    catch {
        $detail = [string]$_.Exception.Message
        $observedHead = $null
        if ($null -ne $resolvedPreview -and (Test-Path -LiteralPath $resolvedPreview -PathType Container)) {
            $observedHead = Get-HermesPreviewObservedHead -Context $context -Checkout $resolvedPreview
        }
        $status = "preview-checkout-unchanged"
        if ($null -ne $observedHead -and $observedHead -eq $resolvedCandidate) {
            $status = switch ($stage) {
                "prepare" { "target-pinned-but-unprepared"; break }
                "validate" { "target-pinned-but-unvalidated"; break }
                "data-attach" { "target-pinned-prepared-sidecar-not-attached"; break }
                default { "target-pinned-but-not-ready"; break }
            }
        }
        throw "Preview UAT failed at stage '$stage'; status=$status; candidate_sha=$resolvedCandidate; fallback=not-attempted; auto-start=not-attempted; db-migration=not-attempted. $detail"
    }
}
