# Registers the DealBot tick in Windows Task Scheduler: every 15 minutes while you are logged on.
# Each tick ends immediately unless a run is due (24h interval or a 지금 새로 찾기 request);
# only then it calls Codex (ChatGPT subscription). See scripts/codex_tick.py.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_tick.ps1            # install / update
#   powershell -ExecutionPolicy Bypass -File scripts\install_tick.ps1 -Uninstall
param([switch]$Uninstall, [int]$Minutes = 15)

$ErrorActionPreference = "Stop"
$name = "DealBot tick"
$repo = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed: $name"
    exit 0
}

$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    & py -3 -m venv (Join-Path $repo ".venv")
    & (Join-Path $repo ".venv\Scripts\python.exe") -m pip install -q -r (Join-Path $repo "requirements.txt")
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "scripts\codex_tick.py" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "DealBot: collect deals when due (scripts/codex_tick.py)" -Force | Out-Null
Write-Output "installed: $name (every $Minutes min, $pythonw scripts\codex_tick.py in $repo)"
