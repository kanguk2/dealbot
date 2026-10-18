# Registers the DealBot tick in Windows Task Scheduler: every 15 minutes while you are logged on.
# Each tick ends immediately unless a run is due (24h interval or a 지금 새로 찾기 request);
# only then it calls Codex (ChatGPT subscription). See scripts/codex_tick.py. Log: .tmp\tick.log
# A tick never runs while the working tree has uncommitted changes (it waits for the next tick).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_tick.ps1            # install / update
#   powershell -ExecutionPolicy Bypass -File scripts\install_tick.ps1 -Uninstall
#   schtasks /Change /TN "DealBot tick" /DISABLE    (or /ENABLE)                  # pause / resume
param([switch]$Uninstall, [int]$Minutes = 15)

$ErrorActionPreference = "Stop"
$name = "DealBot tick"
$repo = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    schtasks /Delete /TN $name /F
    exit $LASTEXITCODE
}

$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    & py -3 -m venv (Join-Path $repo ".venv")
    & (Join-Path $repo ".venv\Scripts\python.exe") -m pip install -q -r (Join-Path $repo "requirements.txt")
}
$script = Join-Path $repo "scripts\codex_tick.py"

# schtasks: interactive (runs only while logged on, so git and Codex use your credentials),
# every N minutes indefinitely. codex_tick.py sets its own working directory.
schtasks /Create /TN $name /SC MINUTE /MO $Minutes /TR "`"$pythonw`" `"$script`"" /IT /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "schtasks failed ($LASTEXITCODE)" }
Write-Output "installed: $name (every $Minutes min) -> $pythonw $script"
