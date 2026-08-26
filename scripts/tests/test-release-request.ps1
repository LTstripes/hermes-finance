# Deterministic tests for the GitHub-native release request/preflight layer.
# No network calls, tags, releases, credentials or private runtime data.

[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$libraryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\release-request-lib.ps1"))
if (-not (Test-Path -LiteralPath $libraryPath -PathType Leaf)) {
    throw "release-request-lib.ps1 not found at '$libraryPath'."
}
. $libraryPath

$script:Passed = 0
$script:Failed = 0
$script:TempRoots = New-Object System.Collections.ArrayList
$script:Version = "0.6.4"
$script:Sha = "0123456789abcdef0123456789abcdef01234567"
$script:ControlIssue = 124
$script:Body = "/release`nversion=$($script:Version)`nexpected_main_sha=$($script:Sha)"

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    if ($Expected -ne $Actual) {
        throw "$Label expected '$Expected', got '$Actual'."
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Case {
    param([Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][scriptblock]$Script)
    try {
        & $Script
        $script:Passed += 1
        Write-Host "PASS: $Name" -ForegroundColor Green
    }
    catch {
        $script:Failed += 1
        Write-Host "FAIL: $Name" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
}

function Invoke-ExpectFailure {
    param([Parameter(Mandatory = $true)][string]$Pattern, [Parameter(Mandatory = $true)][scriptblock]$Script)
    try {
        & $Script
    }
    catch {
        $message = [string]$_.Exception.Message
        if ($message -notmatch $Pattern) {
            throw "Expected failure matching '$Pattern', got '$message'."
        }
        return $message
    }
    throw "Expected failure matching '$Pattern', but the call succeeded."
}

function New-IdentityWorkspace {
    param(
        [string]$ProjectVersion = $script:Version,
        [string]$PackageVersion = $script:Version,
        [switch]$SkipNotes,
        [switch]$EmptyNotes
    )

    $root = Join-Path ([IO.Path]::GetTempPath()) ("hermes-hyg04-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $root | Out-Null
    [void]$script:TempRoots.Add($root)

    $backend = Join-Path $root "backend"
    $package = Join-Path $backend "src\hermes_finance"
    $docs = Join-Path $root "docs"
    New-Item -ItemType Directory -Path $package -Force | Out-Null
    New-Item -ItemType Directory -Path $docs -Force | Out-Null

    [IO.File]::WriteAllText(
        (Join-Path $backend "pyproject.toml"),
        "[project]`nname = `"hermes-finance-backend`"`nversion = `"$ProjectVersion`"`n`n[build-system]`nrequires = []`n",
        (New-Object System.Text.UTF8Encoding $false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $package "__init__.py"),
        "`"`"`"Hermes Finance backend package.`"`"`"`n`n__version__ = `"$PackageVersion`"`n",
        (New-Object System.Text.UTF8Encoding $false)
    )

    if (-not $SkipNotes) {
        $notesText = "Synthetic release notes.`n"
        if ($EmptyNotes) {
            $notesText = ""
        }
        [IO.File]::WriteAllText(
            (Join-Path $docs ("release-notes-{0}.md" -f $script:Version)),
            $notesText,
            (New-Object System.Text.UTF8Encoding $false)
        )
    }

    return $root
}

function Assert-ValidProvenance {
    Assert-HermesReleaseRequestProvenance `
        -Repository "LTstripes/hermes-finance" `
        -Actor "LTstripes" `
        -CommentAuthor "LTstripes" `
        -IssueNumber $script:ControlIssue `
        -ControlIssueNumber $script:ControlIssue `
        -EventName "issue_comment" `
        -EventAction "created"
}

try {
    Invoke-Case "canonical request parses and normalizes exact SHA" {
        $request = Get-HermesReleaseRequest -RequestBody $script:Body
        Assert-Equal -Expected $script:Version -Actual $request.Version -Label "version"
        Assert-Equal -Expected $script:Sha -Actual $request.ExpectedMainSha -Label "sha"
        Assert-Equal -Expected "v$($script:Version)" -Actual $request.Tag -Label "tag"
    }

    Invoke-Case "trailing newline is accepted without widening request grammar" {
        $request = Get-HermesReleaseRequest -RequestBody ($script:Body + "`n")
        Assert-Equal -Expected $script:Version -Actual $request.Version -Label "version"
    }

    Invoke-Case "extra request fields fail closed" {
        Invoke-ExpectFailure -Pattern "exactly three" -Script {
            Get-HermesReleaseRequest -RequestBody ($script:Body + "`nforce=true") | Out-Null
        } | Out-Null
    }

    Invoke-Case "prefixed version fails closed" {
        $body = "/release`nversion=v$($script:Version)`nexpected_main_sha=$($script:Sha)"
        Invoke-ExpectFailure -Pattern "version=X.Y.Z" -Script {
            Get-HermesReleaseRequest -RequestBody $body | Out-Null
        } | Out-Null
    }

    Invoke-Case "short SHA fails closed" {
        $body = "/release`nversion=$($script:Version)`nexpected_main_sha=01234567"
        Invoke-ExpectFailure -Pattern "40-character" -Script {
            Get-HermesReleaseRequest -RequestBody $body | Out-Null
        } | Out-Null
    }

    Invoke-Case "canonical owner provenance passes" {
        Assert-ValidProvenance
    }

    Invoke-Case "wrong actor fails closed" {
        Invoke-ExpectFailure -Pattern "actor" -Script {
            Assert-HermesReleaseRequestProvenance `
                -Repository "LTstripes/hermes-finance" `
                -Actor "someone-else" `
                -CommentAuthor "LTstripes" `
                -IssueNumber $script:ControlIssue `
                -ControlIssueNumber $script:ControlIssue `
                -EventName "issue_comment" `
                -EventAction "created"
        } | Out-Null
    }

    Invoke-Case "wrong comment author fails closed" {
        Invoke-ExpectFailure -Pattern "comment author" -Script {
            Assert-HermesReleaseRequestProvenance `
                -Repository "LTstripes/hermes-finance" `
                -Actor "LTstripes" `
                -CommentAuthor "someone-else" `
                -IssueNumber $script:ControlIssue `
                -ControlIssueNumber $script:ControlIssue `
                -EventName "issue_comment" `
                -EventAction "created"
        } | Out-Null
    }

    Invoke-Case "wrong issue fails closed" {
        Invoke-ExpectFailure -Pattern "only control issue" -Script {
            Assert-HermesReleaseRequestProvenance `
                -Repository "LTstripes/hermes-finance" `
                -Actor "LTstripes" `
                -CommentAuthor "LTstripes" `
                -IssueNumber ($script:ControlIssue + 1) `
                -ControlIssueNumber $script:ControlIssue `
                -EventName "issue_comment" `
                -EventAction "created"
        } | Out-Null
    }

    Invoke-Case "wrong repository fails closed" {
        Invoke-ExpectFailure -Pattern "repository" -Script {
            Assert-HermesReleaseRequestProvenance `
                -Repository "LTstripes/other" `
                -Actor "LTstripes" `
                -CommentAuthor "LTstripes" `
                -IssueNumber $script:ControlIssue `
                -ControlIssueNumber $script:ControlIssue `
                -EventName "issue_comment" `
                -EventAction "created"
        } | Out-Null
    }

    Invoke-Case "wrong event action fails closed" {
        Invoke-ExpectFailure -Pattern "issue_comment/created" -Script {
            Assert-HermesReleaseRequestProvenance `
                -Repository "LTstripes/hermes-finance" `
                -Actor "LTstripes" `
                -CommentAuthor "LTstripes" `
                -IssueNumber $script:ControlIssue `
                -ControlIssueNumber $script:ControlIssue `
                -EventName "issue_comment" `
                -EventAction "edited"
        } | Out-Null
    }

    Invoke-Case "matching repository release identity passes" {
        $root = New-IdentityWorkspace
        $identity = Assert-HermesReleaseIdentity -RepoRoot $root -Version $script:Version
        Assert-Equal -Expected $script:Version -Actual $identity.ProjectVersion -Label "project version"
        Assert-Equal -Expected $script:Version -Actual $identity.PackageVersion -Label "package version"
        Assert-True -Condition (Test-Path -LiteralPath $identity.ReleaseNotes -PathType Leaf) -Message "Release notes path must exist."
    }

    Invoke-Case "wrong pyproject version fails closed" {
        $root = New-IdentityWorkspace -ProjectVersion "0.6.3"
        Invoke-ExpectFailure -Pattern "pyproject.toml version" -Script {
            Assert-HermesReleaseIdentity -RepoRoot $root -Version $script:Version | Out-Null
        } | Out-Null
    }

    Invoke-Case "wrong package version fails closed" {
        $root = New-IdentityWorkspace -PackageVersion "0.6.3"
        Invoke-ExpectFailure -Pattern "__version__" -Script {
            Assert-HermesReleaseIdentity -RepoRoot $root -Version $script:Version | Out-Null
        } | Out-Null
    }

    Invoke-Case "missing canonical release notes fail closed" {
        $root = New-IdentityWorkspace -SkipNotes
        Invoke-ExpectFailure -Pattern "missing" -Script {
            Assert-HermesReleaseIdentity -RepoRoot $root -Version $script:Version | Out-Null
        } | Out-Null
    }

    Invoke-Case "empty canonical release notes fail closed" {
        $root = New-IdentityWorkspace -EmptyNotes
        Invoke-ExpectFailure -Pattern "empty" -Script {
            Assert-HermesReleaseIdentity -RepoRoot $root -Version $script:Version | Out-Null
        } | Out-Null
    }
}
finally {
    foreach ($root in @($script:TempRoots)) {
        if (Test-Path -LiteralPath $root) {
            Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Write-Host "Release request tests: $($script:Passed) passed, $($script:Failed) failed."
if ($script:Failed -ne 0) {
    exit 1
}
