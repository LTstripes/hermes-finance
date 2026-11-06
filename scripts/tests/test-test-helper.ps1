$ErrorActionPreference = 'Stop'
$helper = Join-Path $PSScriptRoot '..\test.ps1'
$output = & powershell.exe -NoProfile -File $helper 2>&1 | Out-String
if ($LASTEXITCODE -ne 2 -or $output -notmatch 'No tests ran') { throw 'Unscoped test helper must refuse without running tests.' }
$output = & powershell.exe -NoProfile -File $helper -Paths 'other/test.py' 2>&1 | Out-String
if ($LASTEXITCODE -eq 0 -or $output -notmatch 'Each selected path') { throw 'Unknown scope must not report success.' }
Write-Host 'Test helper scope checks passed.'
