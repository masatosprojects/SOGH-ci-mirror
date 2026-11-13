param(
    [string]$Config = (Join-Path $PSScriptRoot 'config\monitor.example.json'),
    [string]$State = (Join-Path $env:USERPROFILE 'SOGHRuntime\OfficialMonitor'),
    [switch]$Loop,
    [string]$Export = '',
    [string]$Collab = ''
)
$ErrorActionPreference = 'Stop'
$Config = (Resolve-Path -LiteralPath $Config).Path
[System.IO.Directory]::CreateDirectory($State) | Out-Null
$State = (Resolve-Path -LiteralPath $State).Path
if ([bool]$Export -ne [bool]$Collab) { throw 'Specify both Export and Collab to run version and impact analysis.' }
$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @('-B','-X','utf8','-m','admissions_pipeline.monitor','--restart','--config',('"' + $Config + '"'),'--state',('"' + $State + '"'))
if ($Loop) { $arguments += '--loop' }
if ($Export) {
    $Export = (Resolve-Path -LiteralPath $Export).Path
    $Collab = (Resolve-Path -LiteralPath $Collab).Path
    $arguments += @('--export',('"' + $Export + '"'),'--collab',('"' + $Collab + '"'))
}
$runName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $State ($runName + '.out.log')) -RedirectStandardError (Join-Path $State ($runName + '.err.log'))
$process.Id | Set-Content -LiteralPath (Join-Path $State 'last-process-id.txt') -Encoding ascii
Write-Output ('Monitor started. PID=' + $process.Id + '; State=' + $State + '; Loop=' + [bool]$Loop)
