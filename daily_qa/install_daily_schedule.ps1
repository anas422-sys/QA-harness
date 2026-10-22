$ErrorActionPreference = 'Stop'
$taskName = 'reCheck360 Daily QA Agents'
$runner = 'C:\Users\usama\Downloads\locust\daily_qa\run_daily_qa.cmd'
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $runner + '"')
$trigger = New-ScheduledTaskTrigger -Daily -At '09:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Runs frontend and backend daily QA agents and creates an HTML dashboard.' -Force
Write-Host "Installed: $taskName at 09:00 daily"
