$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $Python) { Write-Error "Python not found"; exit 1 }
$env:BASE_DIL = if ($env:BASE_DIL) { $env:BASE_DIL } else { (Resolve-Path "$ScriptDir\..\..").Path }
& $Python.Source "$ScriptDir\lib\message_tool\message_tool.py" @args
