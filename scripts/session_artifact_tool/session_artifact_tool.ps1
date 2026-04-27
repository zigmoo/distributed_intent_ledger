$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $Python) { Write-Error "Python not found"; exit 4 }

if (-not $env:BASE_DIL) {
    $Candidate = Resolve-Path "$ScriptDir\..\.." -ErrorAction SilentlyContinue
    if ($Candidate) {
        $env:BASE_DIL = $Candidate.Path
    } else {
        Write-Error "Could not resolve DIL base. Set BASE_DIL."
        exit 3
    }
}

$LogDir = Join-Path $env:BASE_DIL "_shared\logs\session_artifact_tool"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Machine = $env:COMPUTERNAME
if (-not $Machine) { $Machine = "unknown" }
$Action = if ($args.Count -gt 0) { $args[0] } else { "help" }
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "$($Machine.ToLower()).session_artifact_tool.$Action.$Timestamp.log"

& $Python.Source "$ScriptDir\lib\session_artifact_tool\session_artifact_tool.py" @args 2>&1 | Tee-Object -FilePath $LogFile -Append
exit $LASTEXITCODE
