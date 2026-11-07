# Synthetic guided OPS02 boundaries: no real checkout, dotenv, DB or listener.
[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../update-stable-guided.ps1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:checks = 0
function Check([bool]$Value, [string]$Label) {
    if (-not $Value) { throw "Guided assertion failed: $Label" }
    $script:checks++
}
function Reject([scriptblock]$Action, [string]$Pattern) {
    $caught = $false
    try { & $Action }
    catch {
        $caught = $true
        Check ($_.Exception.Message -like $Pattern) "expected refusal: $Pattern"
        Check (-not $_.Exception.Message.Contains('synthetic-secret')) 'fixed safe diagnostic'
    }
    Check $caught "refused: $Pattern"
}
$root = Join-Path ([IO.Path]::GetTempPath()) ('hermes-guided-' + [guid]::NewGuid().ToString('N'))
$main = Join-Path $root 'main'
$stable = Join-Path $root 'stable'
foreach ($path in @($main, $stable)) { New-Item -ItemType Directory -Path $path | Out-Null }
$db = Join-Path $root 'Synthetic Data.db'
[IO.File]::WriteAllText($db, 'synthetic database placeholder')
$envFile = Join-Path $stable '.env'
function Write-Selector([string]$Text) { [IO.File]::WriteAllText($envFile, $Text, (New-Object Text.UTF8Encoding($true))) }
$valid = "UNRELATED=synthetic-secret`nOTHER_KEY=synthetic-secret-other-key`nHERMES_FINANCE_DATABASE_PATH='$db' # path only`nOTHER=synthetic-secret-other"
Write-Selector $valid
$realMain = ${function:Assert-HermesGuidedMain}
$realPort = ${function:Assert-HermesGuidedPortFree}

$script:dirty = $false; $script:branch = 'main'; $script:origin = 'https://github.com/LTstripes/hermes-finance.git'
$script:ahead = $false; $script:gitCalls = @(); $script:answers = @(); $script:prompts = 0
function Invoke-HermesGuidedGit {
    param($Main, $Arguments)
    $script:gitCalls += ($Arguments -join ' ')
    switch ($Arguments[0]) {
        'rev-parse' { if ($Arguments[1] -eq '--show-toplevel') { return $Main }; return ('a' * 40) }
        'branch' { return $script:branch }
        'remote' { return $script:origin }
        'status' { if ($script:dirty) { return ' M tracked.txt' }; return '' }
        'merge-base' { if ($script:ahead) { return ('b' * 40) }; return ('a' * 40) }
        'pull' { return '' }
        default { throw 'Unexpected git call' }
    }
}
function Read-Host {
    param($Prompt)
    $script:prompts++
    if ($script:answers.Count -eq 0) { throw 'Unexpected prompt' }
    $answer = $script:answers[0]
    $script:answers = @($script:answers | Select-Object -Skip 1)
    return $answer
}
$script:updates = 0; $script:starts = 0; $script:failUpdate = $false
function Invoke-HermesGuidedUpdate {
    param($Plan)
    Check ($Plan.Database -ceq $db -and $Plan.Backup -eq (Join-Path $root 'Backups/stable-1.2.3-update')) 'explicit updater arguments'
    $script:updates++
    if ($script:failUpdate) { throw 'synthetic update failure' }
}
function Start-HermesGuidedStable { param($Plan) $script:starts++ }
Push-Location $main
try {
    & $realMain $main
    $script:dirty = $true
    Reject { & $realMain $main } '*Main is dirty*'
    $script:dirty = $false; $script:branch = 'task'
    Reject { & $realMain $main } '*main branch*'
    $script:branch = 'main'; $script:origin = 'https://example.invalid/untrusted'
    Reject { & $realMain $main } '*canonical Hermes origin*'
    $script:origin = 'https://github.com/LTstripes/hermes-finance.git'; $script:ahead = $true
    Reject { & $realMain $main } '*local or divergent*'
    $script:ahead = $false
    Check ((Get-HermesGuidedDatabase $stable) -ceq $db) 'only DB selector resolved, BOM supported'
    foreach ($text in @('OTHER_KEY=synthetic-secret', 'HERMES_FINANCE_DATABASE_PATH=relative.db', 'HERMES_FINANCE_DATABASE_PATH=\rooted.db', 'HERMES_FINANCE_DATABASE_PATH=C:relative.db', 'HERMES_FINANCE_DATABASE_PATH=${OTHER_KEY}', "HERMES_FINANCE_DATABASE_PATH='$db'`nHERMES_FINANCE_DATABASE_PATH='$db'", 'HERMES_FINANCE_DATABASE_PATH="synthetic-secret')) {
        Write-Selector $text
        Reject { Get-HermesGuidedDatabase $stable } '*selector*'
    }
    Write-Selector ('HERMES_FINANCE_DATABASE_PATH=' + (Join-Path $root 'missing.db'))
    Reject { Get-HermesGuidedDatabase $stable } '*existing file*'
    Write-Selector $valid
    $plan = Get-HermesGuidedPlan $main '' 'v1.2.3'
    Check ($plan.Stable -eq $stable -and $plan.Version -ceq '1.2.3') 'default Stable and version normalization'
    Reject { Get-HermesGuidedPlan $main $stable '../bad' } '*TargetVersion*'
    New-Item -ItemType Directory -Path $plan.Backup -Force | Out-Null
    Reject { Get-HermesGuidedPlan $main $stable '1.2.3' } '*already exists*'
    # Delete only the exact empty synthetic directory created above.
    [IO.Directory]::Delete($plan.Backup)
    $before = @(Get-ChildItem $root -Recurse -Force | ForEach-Object { $_.FullName }) -join "`n"
    $envHash = (Get-FileHash $envFile).Hash; $dbHash = (Get-FileHash $db).Hash
    function Assert-HermesGuidedPortFree { }
    $script:gitCalls = @()
    $output = Invoke-HermesGuidedOperation $main '' '1.2.3' -DryRun 6>&1 | Out-String -Width 10000
    Check ($output.Contains('-DatabasePath') -and $output.Contains($db) -and $output.Contains('-BackupDirectory')) 'DryRun shows explicit command'
    Check (-not $output.Contains('synthetic-secret') -and -not $output.Contains('UNRELATED') -and -not $output.Contains('OTHER_KEY=')) 'no other dotenv keys or values printed'
    Check ($script:prompts -eq 0 -and $script:updates -eq 0 -and $script:starts -eq 0) 'DryRun has no prompts/update/start'
    Check (@($script:gitCalls | Where-Object { $_ -match 'pull|fetch' }).Count -eq 0) 'DryRun no network/ref mutation'
    Check ($before -ceq (@(Get-ChildItem $root -Recurse -Force | ForEach-Object { $_.FullName }) -join "`n")) 'DryRun creates no files'
    Check ((Get-FileHash $envFile).Hash -ceq $envHash -and (Get-FileHash $db).Hash -ceq $dbHash) 'DryRun leaves inputs unchanged'
    function Assert-HermesGuidedPortFree { throw 'Port 8000 is occupied' }
    Reject { Invoke-HermesGuidedOperation $main $stable '1.2.3' -DryRun } '*Port 8000*'
    function Assert-HermesGuidedPortFree { }
    $script:answers = @('NO')
    Reject { Invoke-HermesGuidedOperation $main $stable '1.2.3' } '*synchronization cancelled*'
    Check (@($script:gitCalls | Where-Object { $_ -like 'pull*' }).Count -eq 0) 'no pull before consent'
    $script:answers = @('PULL', 'wrong')
    Reject { Invoke-HermesGuidedOperation $main $stable '1.2.3' } '*update cancelled*'
    Check ($script:updates -eq 0) 'version confirmation required'
    $script:answers = @('PULL', '1.2.3', 'START')
    Invoke-HermesGuidedOperation $main $stable '1.2.3'
    Check ($script:updates -eq 1 -and $script:starts -eq 1) 'explicit update and separate start'
    $script:failUpdate = $true; $script:answers = @('PULL', '1.2.3')
    Reject { Invoke-HermesGuidedOperation $main $stable '1.2.3' } '*synthetic update failure*'
    Check ($script:starts -eq 1) 'failed update never starts'
}
finally { Pop-Location }
Write-Output "Guided Stable update synthetic regression: PASS ($script:checks checks)"



