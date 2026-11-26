<#
.SYNOPSIS
  Register (or remove) the LiveOS watchdog as a Windows Task Scheduler task.

.DESCRIPTION
  Read this file before running it. It has NOT been run by the agent that wrote it; the
  decision to put a task on this machine is William's (CLAUDE.md: changes to the machine
  wait for his approval). By default the script only PRINTS what it would register. Pass
  -Register to actually create the task, -Unregister to remove it.

  What the task does, exactly:
    command   : <python.exe>  "<repo>\tools\watchdog.py" serve --once
    where     : working directory = the repo root (the parent of this script's folder)
    how often : every 5 minutes, starting one minute after registration, forever
    as whom   : the user running this script (shown below), only while logged on
                (LogonType Interactive), lowest privileges (RunLevel Limited)
    if missed : runs as soon as possible after a missed start (StartWhenAvailable)
    on battery: still runs (the tick is a few file reads)
    overlap   : a new start is skipped while the previous tick still runs
    output    : nothing on screen; the tick writes .local\workflow\watchdog.json every
                run and appends to .local\workflow\watchdog.log only when it finds
                something. `python tools\watchdog.py status` shows the last tick.

  One tick reads runtime state (.local\workflow\*, .local\runs\*) and the ledger
  (workflow\*). It changes the ledger only through tools\coordinator.py (reconcile, or
  one diagnose ticket per overdue attempt). See system\methods\watchdog.md.

  Why Interactive rather than "run whether user is logged on or not": that option stores
  the account password in the task store or needs S4U, and the vault lives in a user
  profile folder. If William wants the watchdog to run while logged off, change
  -LogonType to S4U below; no password is stored with S4U but the task gets no network
  access, which the watchdog does not need.

.PARAMETER Register
  Create or replace the task.
.PARAMETER Unregister
  Remove the task.
.PARAMETER IntervalMinutes
  Minutes between ticks. Default 5 (one minute is the Coordinator's own target when its
  service runs; five is enough for a stand-in that only has to notice and escalate).
.PARAMETER RepoRoot
  The vault root. Default: the parent of this script's folder. Pass it explicitly if the
  watchdog should watch the main checkout instead of a worktree.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\register_watchdog_task.ps1
      shows the exact task it would create, registers nothing

  powershell -ExecutionPolicy Bypass -File tools\register_watchdog_task.ps1 -Register
      registers it

  powershell -ExecutionPolicy Bypass -File tools\register_watchdog_task.ps1 -Unregister
      removes it
#>
[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$Unregister,
    [int]$IntervalMinutes = 5,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$TaskName = "SiyuOS LiveOS Watchdog"
$TaskPath = "\SiyuOS\"
$Watchdog = Join-Path $RepoRoot "tools\watchdog.py"
$User     = "$env:USERDOMAIN\$env:USERNAME"

$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCmd) { $pythonCmd = Get-Command python -ErrorAction SilentlyContinue }
if (-not $pythonCmd) { Write-Error "python.exe not found on PATH; install Python 3.10+ or edit this script to point at it"; exit 1 }
$Python = $pythonCmd.Source

if (-not (Test-Path $Watchdog)) { Write-Error "watchdog not found at $Watchdog"; exit 1 }

Write-Host ""
Write-Host "Task name     : $TaskPath$TaskName"
Write-Host "Command       : `"$Python`" `"$Watchdog`" serve --once"
Write-Host "Working dir   : $RepoRoot"
Write-Host "Interval      : every $IntervalMinutes minute(s), indefinitely; missed starts run when possible"
Write-Host "Run as        : $User (only while logged on; lowest privileges)"
Write-Host "Writes        : $RepoRoot\.local\workflow\watchdog.json (every tick), watchdog.log (findings only)"
Write-Host "Ledger writes : none directly; through tools\coordinator.py only (reconcile, diagnose ticket)"
Write-Host ""

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
        Write-Host "Removed $TaskPath$TaskName"
    } else {
        Write-Host "No task named $TaskPath$TaskName exists; nothing removed"
    }
    exit 0
}

if (-not $Register) {
    Write-Host "Dry run: nothing registered. Re-run with -Register to create this task, -Unregister to remove it."
    Write-Host "To see it afterwards: Get-ScheduledTask -TaskPath '$TaskPath' | Get-ScheduledTaskInfo"
    exit 0
}

$action    = New-ScheduledTaskAction -Execute $Python `
                 -Argument "`"$Watchdog`" serve --once" `
                 -WorkingDirectory $RepoRoot
$trigger   = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
                 -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                 -MultipleInstances IgnoreNew `
                 -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "LiveOS independent watchdog: one tick of tools\watchdog.py. Reads runtime state and the ledger; escalates only through tools\coordinator.py. See system\methods\watchdog.md." `
    -Force | Out-Null

Write-Host "Registered $TaskPath$TaskName. First run in about one minute, then every $IntervalMinutes minute(s)."
Write-Host "Check: python `"$Watchdog`" status      Remove: this script with -Unregister"
