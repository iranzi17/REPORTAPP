# REPORTAPP targeted production update: existing task -> tested GitHub main source.
# No new scheduled task. No REG edits. The pinned V3 snapshot remains untouched.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\maintenance\switch_gap_alerts_to_main.ps1
#        powershell -NoProfile -ExecutionPolicy Bypass -File .\maintenance\switch_gap_alerts_to_main.ps1 -Restore
param([switch]$Restore)
$ErrorActionPreference = 'Stop'
$taskName = 'REPORTAPP Surveyor Quality Alerts'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$src = Join-Path $repo 'outputs\Customer_Meter_Photo_QA_Working\src'
$backupFolder = Join-Path $env:LOCALAPPDATA 'REPORTAPP\Maintenance\main_gap_alerts_switch'
$backup = Join-Path $backupFolder 'previous_task_action.json'
$report = Join-Path $backupFolder 'switch_result.json'
function SaveReport($state, $reason) {
    [pscustomobject]@{
        status=$state
        reason=$reason
        at_utc=(Get-Date).ToUniversalTime().ToString('o')
        watcher_task=$taskName
        config_unchanged=$true
        GIS_unmodified=$true
    } | ConvertTo-Json | Set-Content -LiteralPath $report -Encoding UTF8
    Write-Host ("REPORTAPP: "+$state+" "+$reason)
    Write-Host ("Report: "+$report)
}
function NewAction {
    param(
        [Parameter(Mandatory=$true)][string]$Executable,
        [Parameter(Mandatory=$true)][string]$ArgumentLine,
        [Parameter(Mandatory=$true)][string]$WorkingFolder
    )
    # PowerShell reserves $args for automatic unbound function arguments.
    # A parameter named $args can resolve to an array/empty collection,
    # which ScheduledTasks cannot coerce to its required -Argument string.
    return New-ScheduledTaskAction -Execute $Executable -Argument $ArgumentLine -WorkingDirectory $WorkingFolder
}
function SameAction($actual,$expected) {
    return (($actual.Execute -eq $expected.Execute) -and
            ($actual.Arguments -eq $expected.Arguments) -and
            ($actual.WorkingDirectory -eq $expected.WorkingDirectory))
}
function Test-AllowedArcGISMetadataEdit([string]$entry) {
    # Status format: two position flags, space, repo-relative file path.
    # Deliberately allow ONLY a modified (unstaged) ArcGIS-generated XML.
    # Any staged deletion, rename, executable or config modification blocks.
    if ([string]::IsNullOrWhiteSpace($entry) -or $entry.Length -lt 4) { return $false }
    $state = $entry.Substring(0,2)
    $name = $entry.Substring(3).Replace('\','/')
    return ($state -ceq ' M' -and
        $name -ceq 'outputs/Customer_Meter_Photo_QA_Working/CustomerMeterPhotoQA.pyt.xml')
}
function ReadyTask([int]$seconds=145) {
    $until=(Get-Date).AddSeconds($seconds)
    while ((Get-Date) -le $until) {
        $current = Get-ScheduledTask -TaskName $taskName
        if ([string]$current.State -eq 'Ready') { return $current }
        if ([string]$current.State -ne 'Running') {
            throw 'Existing watcher is not Ready/Running. No task modifications.'
        }
        Start-Sleep -Seconds 4
    }
    throw 'Watcher stayed busy. No task modification. Retry later.'
}
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA unavailable.' }
if (-not (Test-Path $src)) { throw 'Current REPORTAPP source missing.' }
New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null
try {
    $task = ReadyTask
    if ($task.Actions.Count -ne 1) { throw 'Unexpected watcher Action count.' }
    if ($Restore) {
        if (-not (Test-Path $backup)) { throw 'No original action backup. Nothing to restore.' }
        $stored = Get-Content -LiteralPath $backup -Raw | ConvertFrom-Json
        if ($stored.status -ne 'BACKED_UP') { throw 'Unexpected backup state.' }
        $original = NewAction $stored.original.exe $stored.original.args $stored.original.cwd
        $current = $task.Actions[0]
        if (SameAction $current $original) {
            SaveReport 'ORIGINAL_ALREADY_ACTIVE' 'No action change was required.'
            exit 0
        }
        if (-not (SameAction $current (NewAction $stored.target.exe $stored.target.args $stored.target.cwd))) {
            throw 'Task action differs from both original and reviewed main. Refusing to replace it.'
        }
        $answer = Read-Host 'Type RESTORE ORIGINAL WATCHER to restore its original pinned V3 action'
        if ($answer -cne 'RESTORE ORIGINAL WATCHER') { throw 'Operator did not approve restoration.' }
        Set-ScheduledTask -TaskName $taskName -Action $original | Out-Null
        if (-not (SameAction (Get-ScheduledTask -TaskName $taskName).Actions[0] $original)) {
            throw 'Original task action was not verified after restoration.'
        }
        SaveReport 'ORIGINAL_WATCHER_RESTORED' 'Existing one-minute trigger retained.'
        exit 0
    }
    $branch = (& git -C $repo branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw 'Git checkout must be main.' }
    $dirty = @(& git -C $repo status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot check Git working tree status.' }
    # ArcGIS Pro rewrites the tracked companion .pyt.xml toolbox metadata
    # (often a single XML property) during ordinary map/toolbox use.
    # This file is not executable Python, nor watcher configuration.
    # Preserve it IN PLACE rather than stashing, restoring or resetting it.
    # Do not generalize this exception to other XML, Python or task files.
    $otherChanges = @($dirty | Where-Object {
        -not (Test-AllowedArcGISMetadataEdit $_)
    })
    if ($otherChanges.Count -gt 0) {
        throw ('Tracked executable/config/other changes detected; no switch. ' +
               'Only the known locally modified ArcGIS toolbox .pyt.xml is permitted: ' +
               ($otherChanges -join '; '))
    }
    if ($dirty.Count -gt 0) {
        Write-Host 'Preserving ArcGIS toolbox metadata change in place; it is NOT part of the watcher.'
    }
    $head = (& git -C $repo rev-parse HEAD).Trim()
    $origin = (& git -C $repo rev-parse refs/remotes/origin/main).Trim()
    if ($head -ne $origin) { throw 'Local main differs from origin/main. Pull first.' }
    # Presence proof of the actual corrected Windows app identity and recovery.
    $gapCode = Get-Content -Raw -LiteralPath (Join-Path $src 'meter_photo_qa\surveyor_notifications.py')
    $channelCode = Get-Content -Raw -LiteralPath (Join-Path $src 'meter_photo_qa\desktop_toast_channel.py')
    $inboxCode = Get-Content -Raw -LiteralPath (Join-Path $src 'meter_photo_qa\notification_inbox.py')
    if ($gapCode -notmatch 'app_id=DESKTOP_APP_ID' -or
        $channelCode -notmatch 'REPORTAPP Surveyor Activity' -or
        $inboxCode -notmatch 'def resend_saved_alert') {
        throw 'Expected gap-notification correction is missing. Pull latest main.'
    }
    $previous = $task.Actions[0]
    $match = [regex]::Match($previous.Arguments,'--config\s+"([^"]+)"')
    if (-not $match.Success) { throw 'Original watcher config argument not found.' }
    $config = $match.Groups[1].Value
    if (-not (Test-Path -LiteralPath $config)) { throw 'Original monitoring config missing.' }
    $exe = $previous.Execute.Trim('"')
    if ([IO.Path]::GetFileName($exe).ToLowerInvariant() -ne 'pythonw.exe') {
        throw 'Unexpected original Python executable. No task modifications.'
    }
    $interactivePython = Join-Path (Split-Path $exe) 'python.exe'
    if (-not (Test-Path $interactivePython)) { throw 'ArcGIS Pro Python is missing.' }
    $target = NewAction $exe ('-m meter_photo_qa.surveyor_notifications --config "'+$config+'"') $src
    if (SameAction $previous $target) { throw 'Task already uses current source; no switch needed.' }
    # An earlier attempt can save the task Action then abort safely because
    # the GIS service is down. Never overwrite/delete that rollback evidence.
    # Reuse it only if BOTH original and intended new Action match exactly.
    $reuseBackup = $false
    if (Test-Path -LiteralPath $backup) {
        $stored = Get-Content -LiteralPath $backup -Raw | ConvertFrom-Json
        if ($stored.status -ne 'BACKED_UP' -or
            -not $stored.original -or -not $stored.target) {
            throw 'Previous task Action backup is incomplete. No switch.'
        }
        $storedOriginal = NewAction $stored.original.exe $stored.original.args $stored.original.cwd
        $storedTarget = NewAction $stored.target.exe $stored.target.args $stored.target.cwd
        if (-not (SameAction $previous $storedOriginal) -or
            -not (SameAction $target $storedTarget)) {
            throw 'Previous backup and currently verified task/target do not match. No switch.'
        }
        $reuseBackup = $true
        Write-Host 'Verified original task Action backup; it will be reused without modifications.'
    }
    # Offline application preflight only: full national ArcGIS queries are
    # unreliable during REG server incidents. The first actual scheduled
    # cycle, NOT this offline check, must succeed for cutover acceptance.
    Write-Host 'Running local Python/configuration preflight (no REG FeatureServer queries).'
    $env:PYTHONPATH = $src
    $localConfig = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    if ($localConfig.enabled -ne $true -or
        $localConfig.version -ine 'sde.DEFAULT' -or
        $localConfig.channel -ne 'desktop' -or
        @($localConfig.usernames).Count -eq 0 -or
        (@($localConfig.assets) -notcontains 'pole') -or
        (@($localConfig.assets) -notcontains 'line') -or
        (@($localConfig.assets) -notcontains 'transformer')) {
        throw 'Original monitored accounts, assets, enabled state or desktop channel are invalid.'
    }
    & $interactivePython -B -c 'import winotify, arcgis.features; from meter_photo_qa import surveyor_notifications, source_event_navigation, desktop_toast_channel'
    if ($LASTEXITCODE -ne 0) { throw 'Local preflight failed; original task preserved.' }
    Write-Host 'LOCAL_PREFLIGHT_OK: imports/config valid, no GIS queries sent.'
    $answer = Read-Host 'Type ACTIVATE GITHUB MAIN GAP ALERTS to update the existing watcher task'
    if ($answer -cne 'ACTIVATE GITHUB MAIN GAP ALERTS') { throw 'Operator did not approve task change.' }
    if (-not $reuseBackup) {
        $record = [pscustomobject]@{
            status='BACKED_UP'
            head_sha=$head
            original=@{ exe=$previous.Execute; args=$previous.Arguments; cwd=$previous.WorkingDirectory }
            target=@{ exe=$target.Execute; args=$target.Arguments; cwd=$target.WorkingDirectory }
        }
        $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $backup -Encoding UTF8
    }
    $switched = $false
    try {
        $task = ReadyTask
        if (-not (SameAction $task.Actions[0] $previous)) { throw 'Original task changed during preflight.' }
        # Record that replacement was ATTEMPTED before the call: Windows may
        # apply an action even if the management API later raises an error.
        $switched = $true
        Set-ScheduledTask -TaskName $taskName -Action $target | Out-Null
        if (-not (SameAction (Get-ScheduledTask -TaskName $taskName).Actions[0] $target)) {
            throw 'New task action was not verified.'
        }
        # Observe an actual scheduled cycle; never manually run a second scan.
        $log = [IO.Path]::ChangeExtension($config,'.monitor.log')
        $baseline = if (Test-Path $log) { (Get-Item $log).LastWriteTimeUtc } else { [datetime]::MinValue }
        $until = (Get-Date).AddSeconds(195)
        $confirmed = $false
        while ((Get-Date) -lt $until) {
            Start-Sleep -Seconds 5
            if (Test-Path $log) {
                $file = Get-Item $log
                $last = @(Get-Content $log -Tail 2)
                if ($file.LastWriteTimeUtc -gt $baseline -and
                    ($last | Where-Object { $_ -match "records_scanned" -and $_ -match "alerts_delivery_failed" })) {
                    $confirmed = $true
                    break
                }
            }
        }
        if (-not $confirmed) { throw 'No successful scheduled cycle confirmed. Rolling back.' }
        SaveReport 'MAIN_WATCHER_FIRST_CYCLE_OK' 'Live gap alerts now use current checked-out GitHub main.'
    } catch {
        # No REG/SQLite data is ever changed by this task-action restore.
        $originalError = $_.Exception.Message
        if ($switched) {
            try {
                $t = ReadyTask
                if (SameAction $t.Actions[0] $target) {
                    Set-ScheduledTask -TaskName $taskName -Action $previous | Out-Null
                }
                if (-not (SameAction (Get-ScheduledTask -TaskName $taskName).Actions[0] $previous)) {
                    throw 'Exact original Task Scheduler action was not restored.'
                }
            } catch {
                SaveReport 'ROLLBACK_REQUIRES_REVIEW' $_.Exception.Message
                throw
            }
        }
        SaveReport 'CUTOVER_ABORTED_OR_ROLLED_BACK' $originalError
        throw
    }
} catch {
    Write-Error ("REPORTAPP watcher switch aborted: "+$_.Exception.Message)
    exit 2
}
