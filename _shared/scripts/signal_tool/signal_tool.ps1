$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $Python) { Write-Error "Python not found"; exit 1 }
& $Python.Source "$ScriptDir\lib\signal_tool\signal_tool.py" @args
