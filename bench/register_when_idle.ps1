# Register the fps-sweep watcher as a scheduled task at logon, start it now, and prove it by effect.
#
# Why a task and not a hand launch: the watcher started by hand on 2026-09-11 died with the
# night (the log stops at 23:07, no farewell) and nothing brought it back.  A task at logon
# with StartWhenAvailable is the pattern Bocado proved after a shutdown.
#
# Rules of this machine baked in: the executable is the venv's pythonw.exe by absolute path
# (no console at all, so nothing can appear over a game; never a versioned WindowsApps path),
# the task may start and keep running on battery, has no time limit, and never stacks a
# second instance.  Proof is the effect, not the state: a fresh "start" line in the log and a
# live pythonw with when_idle.py on its command line.  `Ready` and `0x0` prove nothing.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File bench\register_when_idle.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pyw = Join-Path $repo ".venv\Scripts\pythonw.exe"
$script = Join-Path $repo "bench\when_idle.py"
$log = Join-Path $repo "out\fps_sweep\when_idle.log"
$name = "levanta - barrido fps cuando no haya juego"

if (-not (Test-Path $pyw)) { throw "interpreter missing: $pyw" }
if (-not (Test-Path $script)) { throw "watcher missing: $script" }
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

$before = if (Test-Path $log) { (Get-Content $log | Measure-Object -Line).Lines } else { 0 }

$action = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '" C:/Users/jhona/arkitscenes_data/raw/Validation out/fps_sweep --poll 60') -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
$desc = "Waits until the card is free (no game rendering, GPU under 25 %) and runs bench/fps_sweep.py one fps at a time. Writes only under out/fps_sweep. Registered 2026-09-12."
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description $desc -Force | Out-Null
Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 10

$t = Get-ScheduledTask -TaskName $name
$i = Get-ScheduledTaskInfo -TaskName $name
"task '$name'"
"  state          : " + $t.State
"  last result    : " + ('0x{0:X}' -f $i.LastTaskResult) + "  (proves nothing on its own)"
"  last run       : " + $i.LastRunTime
"  next run       : " + $i.NextRunTime + "  (empty is normal for a logon trigger)"
"  action exists  : " + (Test-Path $t.Actions[0].Execute) + "  " + $t.Actions[0].Execute
"  triggers       : " + (($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ", ")
"  on battery ok  : " + (-not $t.Settings.DisallowStartIfOnBatteries) + " / keeps running: " + (-not $t.Settings.StopIfGoingOnBatteries)
"  start when avail: " + $t.Settings.StartWhenAvailable
$after = (Get-Content $log | Measure-Object -Line).Lines
"effect: log lines before/after start = $before / $after"
"  tail:"
Get-Content $log -Tail 3 | ForEach-Object { "    " + $_ }
$procs = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object { $_.CommandLine -like "*when_idle.py*" }
"  watcher process: " + (($procs | ForEach-Object { "PID " + $_.ProcessId + " " + $_.ExecutablePath }) -join "; ")
$windows = (Get-Process -Name python, pythonw, cmd, conhost -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Measure-Object).Count
"  visible console windows (python/pythonw/cmd/conhost): $windows"
if ($after -le $before) { throw "no new line in the log: the task started nothing" }
if (-not $procs) { throw "no pythonw running when_idle.py: the task started nothing" }
