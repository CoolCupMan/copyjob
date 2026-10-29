# Optional permanent local WMI wake-up hook for one CopyJob scheduled user task.
# Run as administrator. No copy command or writable script runs as SYSTEM.
#Requires -RunAsAdministrator
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = '__TASK_NAME__'
$name = $taskName + '-VolumeWake'
$assignmentTask = $taskName + '-AssignLetters'
$ns = 'root\subscription'
$filter = Get-WmiObject -Namespace $ns -Class __EventFilter -Filter "Name='$name'"
$consumer = Get-WmiObject -Namespace $ns -Class CommandLineEventConsumer -Filter "Name='$name'"
Get-WmiObject -Namespace $ns -Class __FilterToConsumerBinding | Where-Object {
    ($filter -and $_.Filter -eq $filter.__PATH) -or ($consumer -and $_.Consumer -eq $consumer.__PATH)
} | Remove-WmiObject
if ($consumer) { $consumer | Remove-WmiObject }
if ($filter) { $filter | Remove-WmiObject }
if ($Remove) {
    if (Get-ScheduledTask -TaskName $assignmentTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $assignmentTask -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $assignmentTask -Confirm:$false
    }
    Write-Host "Removed WMI wake hook for $taskName"; return }
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.Principal.RunLevel -notin @(0,'Limited') -or $task.Principal.LogonType -notin @(3,'Interactive')) {
    throw 'Expected the limited interactive CopyJob task. Enable login startup in CopyJob first.'
}
$filter = Set-WmiInstance -Namespace $ns -Class __EventFilter -Arguments @{
    Name=$name; EventNamespace='root\cimv2'; QueryLanguage='WQL'
    Query="SELECT * FROM __InstanceCreationEvent WITHIN 5 WHERE TargetInstance ISA 'Win32_LogicalDisk'"
}
$exe = Join-Path $env:SystemRoot 'System32\schtasks.exe'
try {
    $consumer = Set-WmiInstance -Namespace $ns -Class CommandLineEventConsumer -Arguments @{
        Name=$name; ExecutablePath=$exe
        CommandLineTemplate=('"{0}" /Run /TN "{1}"' -f $exe,$taskName)
    }
    Set-WmiInstance -Namespace $ns -Class __FilterToConsumerBinding -Arguments @{
        Filter=$filter; Consumer=$consumer
    } | Out-Null
} catch {
    if ($consumer) { $consumer | Remove-WmiObject }
    $filter | Remove-WmiObject
    throw
}
Write-Host "Installed WMI wake hook for $taskName. Login task and polling cover startup and later letter assignments."

# Optional preferred-letter enforcement uses an immutable encoded task action.
# No EXE, PS1 or JSON file in the user's writable installation runs as SYSTEM.
$assignmentData = '__ASSIGNMENTS_JSON_B64__'
$bindings = @([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($assignmentData)) | ConvertFrom-Json)
if (Get-ScheduledTask -TaskName $assignmentTask -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $assignmentTask -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $assignmentTask -Confirm:$false
}
if ($bindings.Count -gt 0) {
    $payload = @'
$ErrorActionPreference='Stop'
$bindings=@([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__DATA__')) | ConvertFrom-Json)
while ($true) {
    try {
        $volumes=@(Get-CimInstance Win32_Volume)
        foreach ($binding in $bindings) {
            $volume=$volumes | Where-Object DeviceID -EQ $binding.volume
            if (!$volume -or $volume.BootVolume -or $volume.SystemVolume) { continue }
            if ($volume.DriveLetter -eq $binding.letter) { continue }
            $occupied=$volumes | Where-Object DriveLetter -EQ $binding.letter
            if (!$occupied) {
                Set-CimInstance -InputObject $volume -Property @{DriveLetter=$binding.letter} | Out-Null
                $volumes=@(Get-CimInstance Win32_Volume)
            }
        }
    } catch {
        # Retry transient failures; Task Scheduler retains process failure diagnostics.
    }
    Start-Sleep -Seconds 5
}
'@
    $payload=$payload.Replace('__DATA__',$assignmentData)
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($payload))
    $action=New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\WindowsPowerShell1.0\powershell.exe') -Argument ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand '+$encoded)
    $trigger=New-ScheduledTaskTrigger -AtStartup
    $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $assignmentTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $assignmentTask
    Write-Host 'Preferred-letter startup task installed. Occupied letters and system volumes are preserved.'
}
