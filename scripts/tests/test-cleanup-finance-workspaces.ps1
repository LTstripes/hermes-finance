$ErrorActionPreference='Stop'
$script=(Resolve-Path (Join-Path $PSScriptRoot '..\cleanup-finance-workspaces.ps1')).Path
$root=Join-Path $env:TEMP ('hermes-cleanup-'+[guid]::NewGuid().ToString('N'))
$finance=Join-Path $root 'finance';$stable=Join-Path $finance 'hermes-finance-runtime';$preview=Join-Path $finance 'hermes-finance-preview-r07';$cache=Join-Path $finance '.uv-cache-old';$guarded=Join-Path $finance 'pytest-guarded';$config=Join-Path $root 'config.json'
try{
    New-Item -ItemType Directory -Path $stable,$preview,$cache,$guarded -Force|Out-Null
    Set-Content (Join-Path $cache 'cache.bin') 'discardable';Set-Content (Join-Path $guarded 'test.db') 'synthetic'
    @{profiles=@(@{checkout=$stable;database=(Join-Path $stable 'finance.db')},@{checkout=$preview;database=(Join-Path $preview 'finance.db')})}|ConvertTo-Json -Depth 5|Set-Content $config
    $dry=& $script -FinanceRoot $finance -LauncherConfigPath $config -SkipGitWorktrees
    if(-not(Test-Path $cache)){throw 'dry-run removed cache'}
    if(@($dry.candidates|Where-Object path -eq $cache).Count-ne1){throw 'safe cache not reported'}
    if(@($dry.keep|Where-Object path -eq $guarded).Count-ne1){throw 'database parent not kept'}
    $applied=& $script -FinanceRoot $finance -LauncherConfigPath $config -SkipGitWorktrees -Apply
    if(Test-Path $cache){throw 'apply did not remove cache'}
    if(-not(Test-Path $guarded)-or-not(Test-Path $stable)-or-not(Test-Path $preview)-or-not(Test-Path $config)){throw 'protected path changed'}
    'PASS: cleanup dry-run/apply protection probe'
}finally{if(Test-Path $root){Remove-Item -LiteralPath $root -Recurse -Force}}
