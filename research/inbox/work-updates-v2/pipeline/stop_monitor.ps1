param([string]$State = (Join-Path $env:USERPROFILE 'SOGHRuntime\OfficialMonitor'))
$ErrorActionPreference = 'Stop'
[System.IO.Directory]::CreateDirectory($State) | Out-Null
[System.IO.File]::WriteAllText((Join-Path $State 'STOP'), 'stop requested')
Write-Output 'Safe stop requested. The current bounded fetch/analysis finishes before exit. No process is force-killed.'
