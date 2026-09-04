<#
.SYNOPSIS
Safely inventories and removes disposable Hermes Finance Windows workspaces.
.DESCRIPTION
Dry-run by default. -Apply repeats every safety check before removal. The
script never reads .env or SQLite contents; it inspects names and metadata only.
#>
[CmdletBinding()]
param(
    [string]$FinanceRoot = 'D:\Finance',
    [string]$RepositoryPath = 'D:\Finance\hermes-finance-codex',
    [string]$LauncherConfigPath = (Join-Path $env:LOCALAPPDATA 'HermesFinance\launcher\config.json'),
    [switch]$RefreshRemote,
    [switch]$Apply,
    [switch]$SkipGitWorktrees
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Apply -and -not $SkipGitWorktrees -and -not $RefreshRemote) {
    throw '-Apply for Git worktree cleanup requires explicit -RefreshRemote. Use -Apply -SkipGitWorktrees for artifact-only cleanup.'
}

function Normalize([string]$Path) { [IO.Path]::GetFullPath($Path).TrimEnd('\') }
function IsWithin([string]$Path,[string]$Root) {
    $p=Normalize $Path; $r=Normalize $Root
    $p -eq $r -or $p.StartsWith($r+'\',[StringComparison]::OrdinalIgnoreCase)
}
function IsProtectedFile($File) {
    $File.Name -eq '.env' -or $File.Extension -in @('.db','.sqlite','.sqlite3') -or
        $File.Name -match '(?i)\.(db|sqlite|sqlite3)-(wal|shm|journal)$'
}
function InspectTree([string]$Path) {
    $bytes=[int64]0; $protected=0; $reparse=0; $failure=$null
    try {
        $root=Get-Item -LiteralPath $Path -Force
        if($root.Attributes -band [IO.FileAttributes]::ReparsePoint){$reparse++}
        $items=if($root.PSIsContainer){Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop}else{@($root)}
        foreach($item in $items){
            if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){$reparse++}
            if(-not $item.PSIsContainer){$bytes += [int64]$item.Length;if(IsProtectedFile $item){$protected++}}
        }
    } catch {$failure=$_.Exception.Message}
    [pscustomobject]@{bytes=$bytes;protected=$protected;reparse=$reparse;failure=$failure}
}
function ConfigPaths($Value,[string]$Key='') {
    $result=[Collections.Generic.List[string]]::new()
    if($null -eq $Value){return @()}
    if($Value -is [pscustomobject]){
        foreach($p in $Value.PSObject.Properties){$next=if($Key){"$Key.$($p.Name)"}else{$p.Name};foreach($v in ConfigPaths $p.Value $next){$result.Add($v)}}
    } elseif(($Value -is [Collections.IEnumerable]) -and -not ($Value -is [string])){
        foreach($entry in $Value){foreach($v in ConfigPaths $entry $Key){$result.Add($v)}}
    } elseif($Value -is [string] -and $Key -match '(?i)(checkout|database|db.*path|path.*db)' -and [IO.Path]::IsPathRooted($Value)){
        $result.Add((Normalize $Value))
    }
    @($result|Sort-Object -Unique)
}
function Git([string]$Path,[string[]]$GitArgs,[switch]$AllowFailure){
    $safe='safe.directory='+((Normalize $Path)-replace '\\','/')
    $out=@(& git.exe -c $safe -C $Path @GitArgs 2>&1);$code=$LASTEXITCODE
    if(-not $AllowFailure -and $code -ne 0){throw "git $($GitArgs -join ' ') failed ($code): $($out -join ' ')"}
    [pscustomobject]@{out=$out;code=$code}
}
function AddEvidence($List,[string]$Path,[string]$Reason){$List.Add([pscustomobject]@{path=$Path;reason=$Reason})}

$finance=Normalize $FinanceRoot;$repository=Normalize $RepositoryPath;$launcher=Normalize $LauncherConfigPath
if(-not(Test-Path -LiteralPath $finance -PathType Container)){throw "Missing finance root: $finance"}
if(-not(Test-Path -LiteralPath $launcher -PathType Leaf)){throw "Missing launcher config: $launcher"}
$configured=@(ConfigPaths (Get-Content -LiteralPath $launcher -Raw|ConvertFrom-Json))
$stable=Normalize (Join-Path $finance 'hermes-finance-runtime')
$preview=Normalize (Join-Path $finance 'hermes-finance-preview-r07')
$ownerProbes=Normalize (Join-Path $finance 'owner-probes')
$hardProtected=@($stable,$preview,$ownerProbes)
if(-not(Test-Path -LiteralPath $stable -PathType Container) -or -not(Test-Path -LiteralPath $preview -PathType Container)){throw 'Canonical Stable or Preview checkout is missing.'}
if($stable -notin $configured -or $preview -notin $configured){throw 'Launcher config does not reference canonical Stable and Preview checkouts.'}

$originMain=$null
if(-not $SkipGitWorktrees){
    if(-not(Test-Path -LiteralPath $repository -PathType Container)){throw "Missing repository: $repository"}
    if($RefreshRemote){[void](Git -Path $repository -GitArgs @('fetch','origin'))}
    $originMain=[string](Git -Path $repository -GitArgs @('rev-parse','origin/main')).out[0]
}
$candidates=[Collections.Generic.List[object]]::new();$keep=[Collections.Generic.List[object]]::new();$unknown=[Collections.Generic.List[object]]::new()
function ConsiderArtifact($Item,[string]$Kind){
    $ev=InspectTree $Item.FullName
    if($ev.failure){AddEvidence $unknown $Item.FullName "scan failed: $($ev.failure)"}
    elseif($ev.protected){AddEvidence $keep $Item.FullName "contains $($ev.protected) protected .env/database files"}
    elseif($ev.reparse){AddEvidence $unknown $Item.FullName 'contains reparse point'}
    else{$candidates.Add([pscustomobject]@{path=$Item.FullName;kind=$Kind;bytes=$ev.bytes;head=$null;branch=$null;remoteHead=$null})}
}
foreach($item in Get-ChildItem -LiteralPath $finance -Force){
    if($item.PSIsContainer -and $item.Name -match '^(?i)(\.uv-cache|pytest|_pytest|\.pytest|hermes-test-temp)'){ConsiderArtifact $item 'disposable-test-or-cache'}
    elseif(-not $item.PSIsContainer -and $item.Name -match '^(?i)frontend-vitest-.*\.json$'){ConsiderArtifact $item 'test-output'}
}
$scratch=Join-Path $finance 'scratch'
if(Test-Path -LiteralPath $scratch -PathType Container){foreach($item in Get-ChildItem -LiteralPath $scratch -Force -Directory|Where-Object Name -Like 'uv-cache*'){ConsiderArtifact $item 'uv-cache'}}

if(-not $SkipGitWorktrees){
    $parsed=[Collections.Generic.List[object]]::new();$current=$null
    foreach($line in @((Git -Path $repository -GitArgs @('worktree','list','--porcelain')).out)+@('')){
        if($line -like 'worktree *'){$current=[ordered]@{path=Normalize $line.Substring(9);head=$null;branch='(detached)'}}
        elseif($null-ne$current -and $line -like 'HEAD *'){$current.head=$line.Substring(5)}
        elseif($null-ne$current -and $line -like 'branch refs/heads/*'){$current.branch=$line.Substring(18)}
        elseif($null-ne$current -and $line -eq ''){$parsed.Add([pscustomobject]$current);$current=$null}
    }
    foreach($wt in $parsed){
        if($wt.path -eq $repository){AddEvidence $keep $wt.path 'common repository root';continue}
        if($hardProtected|Where-Object{IsWithin $wt.path $_}){AddEvidence $keep $wt.path 'hard-protected runtime/owner path';continue}
        if($configured|Where-Object{IsWithin $_ $wt.path}){AddEvidence $keep $wt.path 'launcher-configured path';continue}
        $ev=InspectTree $wt.path
        if($ev.failure){AddEvidence $unknown $wt.path "scan failed: $($ev.failure)";continue}
        if($ev.protected){AddEvidence $keep $wt.path 'contains protected .env/database files';continue}
        if($ev.reparse){AddEvidence $unknown $wt.path 'contains reparse point';continue}
        $status=Git -Path $wt.path -GitArgs @('status','--porcelain=v1','--untracked-files=all') -AllowFailure
        if($status.code){AddEvidence $unknown $wt.path 'git status failed';continue}
        if($status.out.Count){AddEvidence $keep $wt.path 'dirty worktree';continue}
        if((Git -Path $repository -GitArgs @('merge-base','--is-ancestor',$wt.head,'origin/main') -AllowFailure).code){AddEvidence $keep $wt.path 'local HEAD is unmerged';continue}
        $remoteHead=$null
        if($wt.branch -ne '(detached)'){
            $remote=Git -Path $repository -GitArgs @('rev-parse','--verify',"refs/remotes/origin/$($wt.branch)") -AllowFailure
            if($remote.code){AddEvidence $unknown $wt.path 'named branch has no fetched origin ref';continue}
            $remoteHead=[string]$remote.out[0]
            if((Git -Path $repository -GitArgs @('merge-base','--is-ancestor',$remoteHead,'origin/main') -AllowFailure).code){AddEvidence $keep $wt.path 'origin branch is unmerged';continue}
        }
        $candidates.Add([pscustomobject]@{path=$wt.path;kind='git-worktree';bytes=$ev.bytes;head=$wt.head;branch=$wt.branch;remoteHead=$remoteHead})
    }
}
$estimated=[int64]0
foreach($candidateSize in $candidates){$estimated += [int64]$candidateSize.bytes}
Write-Host "Mode: $(if($Apply){'APPLY'}else{'DRY-RUN'})"
Write-Host "origin/main: $originMain"
Write-Host ("Candidates: {0}; estimated reclaim: {1:N3} GiB" -f $candidates.Count,($estimated/1GB))
$candidates|Sort-Object path|Select-Object path,kind,@{n='GiB';e={[math]::Round($_.bytes/1GB,3)}}|Format-Table -AutoSize|Out-Host
Write-Host "KEEP: $($keep.Count); UNKNOWN: $($unknown.Count)"
$removed=[Collections.Generic.List[object]]::new();$blocked=[Collections.Generic.List[object]]::new()
if($Apply){foreach($candidate in $candidates){try{
    $path=Normalize $candidate.path
    if(-not(IsWithin $path $finance) -or $path -eq $finance){throw 'outside finance root boundary'}
    if($hardProtected|Where-Object{IsWithin $path $_}){throw 'inside hard-protected runtime/owner path'}
    if($configured|Where-Object{IsWithin $_ $path}){throw 'contains launcher-configured path'}
    $fresh=InspectTree $path
    if($fresh.failure){throw "fresh scan failed: $($fresh.failure)"};if($fresh.protected){throw 'fresh scan found protected file'};if($fresh.reparse){throw 'fresh scan found reparse point'}
    if($candidate.kind -eq 'git-worktree'){
        $head=[string](Git -Path $path -GitArgs @('rev-parse','HEAD')).out[0];if($head-ne$candidate.head){throw 'HEAD changed'}
        if((Git -Path $path -GitArgs @('status','--porcelain=v1','--untracked-files=all')).out.Count){throw 'worktree became dirty'}
        if((Git -Path $repository -GitArgs @('merge-base','--is-ancestor',$head,'origin/main') -AllowFailure).code){throw 'HEAD became unmerged'}
        if($candidate.remoteHead){$freshRemote=[string](Git -Path $repository -GitArgs @('rev-parse','--verify',"refs/remotes/origin/$($candidate.branch)")).out[0];if($freshRemote-ne$candidate.remoteHead){throw 'origin branch changed'}}
        [void](Git -Path $repository -GitArgs @('worktree','remove','--',$path))
    }else{Remove-Item -LiteralPath $path -Recurse -Force}
    if(Test-Path -LiteralPath $path){throw 'path remains after operation'};$removed.Add($candidate)
}catch{AddEvidence $blocked $candidate.path $_.Exception.Message}}}
if($Apply -and $blocked.Count -eq 0 -and -not $SkipGitWorktrees){[void](Git -Path $repository -GitArgs @('worktree','prune','--verbose'))}
[pscustomobject]@{mode=if($Apply){'apply'}else{'dry-run'};originMain=$originMain;candidates=@($candidates);estimatedReclaimBytes=$estimated;keep=@($keep);unknown=@($unknown);removed=@($removed);blocked=@($blocked)}
