<#
REPORTAPP Self-Maintenance (opt-in, current Windows user, no admin rights).
Creates a separate 10-minute scheduled task. Never replaces the surveyor watcher.
Explicit -EnableAutoDeploy authorizes installation of eligible approved releases.
Optional -EnableGitHubIssueReporting requires an authenticated GitHub CLI.
#>
param(
    [switch]$EnableAutoDeploy,
    [switch]$EnableGitHubIssueReporting
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$script = Join-Path $PSScriptRoot 'self_monitor.py'
$python = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'ArcGIS Pro Python was not found at the expected location.'
}
if (-not (Test-Path -LiteralPath $script)) {
    throw 'REPORTAPP maintenance source missing.'
}
if ($EnableGitHubIssueReporting) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw 'GitHub CLI (gh) must be installed and authenticated before enabling issue reports.'
    }
    & gh auth status --hostname github.com
    if ($LASTEXITCODE -ne 0) {
        throw 'Run gh auth login before enabling issue reports.'
    }
}
$root = Join-Path $env:LOCALAPPDATA 'REPORTAPP\Maintenance'
New-Item -Path $root -ItemType Directory -Force | Out-Null
$policyPath = Join-Path $root 'policy.json'
if (Test-Path -LiteralPath $policyPath) {
    $old = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json
    if ([bool]$old.auto_deploy -ne [bool]$EnableAutoDeploy -or [bool]$old.github_issue_reporting -ne [bool]$EnableGitHubIssueReporting) {
        throw 'Existing policy differs. Review policy.json manually; existing policy was preserved.'
    }
} else {
    $policy = @{
        auto_deploy = [bool]$EnableAutoDeploy
        github_issue_reporting = [bool]$EnableGitHubIssueReporting
        allowed_updates = @('notification_inbox.py')
        repository = 'iranzi17/REPORTAPP'
    } | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($policyPath, $policy + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
}
& $python $script --status
if ($LASTEXITCODE -ne 0) { throw 'Health preflight failed.' }

$taskName = 'REPORTAPP Self Maintenance'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host 'Maintenance task already exists; not overwritten.'
    return
}
$pyw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pyw)) { $pyw = $python }
$action = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '" --cycle') -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Host ('REPORTAPP Self Maintenance installed. Auto-deploy=' + [bool]$EnableAutoDeploy + '; GitHub issue reporting=' + [bool]$EnableGitHubIssueReporting)
Write-Host ('Health snapshot: ' + (Join-Path $root 'health_latest.json'))
Write-Host 'Existing REPORTAPP Surveyor Quality Alerts task was not changed.'
