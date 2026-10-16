# REPORTAPP v2 — Guarded unattended watcher updates

**Current clean activity behavior:** REPORTAPP stores per-asset QA-clean surveyor
events in SQLite and shows **one combined desktop toast every 30 minutes**,
instead of one toast per pole, line or transformer. Individual features remain
available for click-to-zoom through Clean Activity History; error alerts are
still immediate. A failed digest does not erase pending records.

If the office **Install Approved Update** button previously refused because
unrelated tracked files were modified, the revised Inbox UI permits a guarded
fast-forward when those local edits do not overlap incoming changed files.
It refuses conflicting paths and never discards local work. The Inbox-only
bootstrap release `reportapp-safe-v20261016-002` delivers this change to the
existing v1 maintainer automatically; reopen the Inbox and click the upgrade
button once, confirming the prompt. This is a supervised bootstrap, not a
remote assertion that the office computer has already upgraded.


The office currently runs Self Maintenance v1, which intentionally updates only the Inbox UI.
An automatically published Inbox-only bootstrap release brings a new **Install Approved Update**
button to the Inbox; restart the Inbox after the release has been installed.
Click that button once to approve the verified fast-forward from main, file backups,
and local regression tests. No terminal commands or changes to REG data are required.

After that one-time approved upgrade, the same local scheduled maintenance task
can install narrow CI-tested reportapp-watcher releases, with SHA256 verification,
backups, smoke tests and rollback. Only designated Python watcher/Inbox files
and tests are allowlisted; GIS service settings, watched accounts, credentials,
SQLite monitoring history, source feature attributes, and ArcGIS add-in DLLs
remain protected. V1 ignores watcher releases, even when those releases exist.

The **Site Status** Inbox control determines when yesterday's and older QA
notifications may be delivered. On-site status is assumed until working hours
or an explicit off-site status is set. New same-day quality alerts continue normally.

## Original v1 installation instructions (historical reference)
# REPORTAPP Self-Maintenance — v1 (restricted rollout)

**Status: source and GitHub CI. Office workstation activation requires explicit
installation. No automatic deployment takes place until enabled on that PC.**

This maintenance system is deliberately separate from the live
\`REPORTAPP Surveyor Quality Alerts\` scheduled task. It never writes REG
features, deletes notification history, changes monitored accounts, resets
activation dates, or performs unattended \`git pull\`.

## Functions

- Every 10 minutes, a local Windows scheduled task records an aggregate health
  snapshot at \`%LOCALAPPDATA%\REPORTAPP\Maintenance\health_latest.json\`.
  The snapshot contains task state, recent scan age/counts, delivery failure
  count, and pending navigation request count, **not GIS feature values,
  usernames, credentials, or raw error logs**.
- Opt-in sanitized GitHub issue reporting calls the user's authenticated
  \`gh issue create\` only for unhealthy status; issue codes are deduplicated
  locally for 12 hours. **Do not enable this for confidential environments
  without organizational approval.** It does not share raw diagnostics.
- Opt-in automatic deployment checks published GitHub Releases whose tags
  match \`reportapp-safe-vYYYYMMDD-NNN\`. A release is created only through
  an explicitly initiated **Publish approved REPORTAPP safe UI release**
  GitHub workflow on \`main\` after focused CI tests. The updater requires
  the GitHub asset SHA256 digest, checks archive paths and per-file hashes,
  writes backups, and runs local regression tests.
- **Only**
  \`outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/notification_inbox.py\`
  is currently auto-deploy eligible. It is safe for the Inbox GUI to be
  restarted to pick up the update. The live watcher, scripts that generate
  quality notifications, quality rules, add-in DLL/installer, GIS connections,
  \`monitor_config.json\`, SQLite files, GIS layers and credentials are all
  **excluded** from unattended deployment.

## One-time activation on the office computer

1. Review this code and the approved scope with your IT/GIS supervisor.
   After it is merged to \`main\`, confirm local \`git status --short\` and
   perform an explicit \`git pull --ff-only origin main\`; do not overwrite
   uncommitted local files.
2. Open PowerShell (no administrator rights needed) and run:

   \`\`\`powershell
   cd 'C:\Users\AKIOLI TECHNOLOGY\Desktop\REPORTAPP'
   .\maintenance\Install-SelfMonitor.ps1 -EnableAutoDeploy
   \`\`\`

   To additionally publish **sanitized** GitHub issues, install and authenticate
   GitHub CLI using \`gh auth login\` and then choose both switches on the
   **initial** install:

   \`\`\`powershell
   .\maintenance\Install-SelfMonitor.ps1 -EnableAutoDeploy -EnableGitHubIssueReporting
   \`\`\`

   The reporting switch is optional; remote diagnosis is unavailable without
   it. GitHub CLI should have access to create issues in \`iranzi17/REPORTAPP\`.
   Do not put a personal access token in a JSON file or script.
3. Inspect local status:

   \`\`\`powershell
   & 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' .\maintenance\self_monitor.py --status
   Get-Content "$env:LOCALAPPDATA\REPORTAPP\Maintenance\cycle_latest.json"
   Get-ScheduledTask -TaskName 'REPORTAPP Self Maintenance'
   \`\`\`

The task runs only in the current interactive Windows user context. It is not
capable of installing C# ArcGIS Pro add-ins or altering protected GIS rules.

## Approval and release process

1. Fixes are prepared in development branches and checked by CI.
2. Merge an approved fix into \`main\` after review.
3. In GitHub Actions, **manually** run the
   \`Publish approved REPORTAPP safe UI release\` workflow from \`main\`
   with an unused tag, for example \`reportapp-safe-v20261016-001\`.
4. The workflow runs safety and Inbox regression tests, packages exactly one
   allowlisted source file, and publishes a versioned GitHub release.
5. The office maintenance task picks up the **approved published release**
   on its next cycle, validates the GitHub release digest and bundled file
   hashes, makes backups, installs the Inbox Python file, and runs focused
   regression tests. If tests fail, it immediately restores original bytes
   and blocks that release from further automatic attempts.

Publishing an update is a **human promotion step**. The computer does not
install arbitrary commits, unseen pull requests, unreviewed fixes, or
updates from a different repository. Already-open Inbox windows need
to be closed and reopened to load updated code.

## Monitoring / failures / rollback

- Current data: \`%LOCALAPPDATA%\REPORTAPP\Maintenance\health_latest.json\`
- Latest cycle / deployment failure type:
  \`%LOCALAPPDATA%\REPORTAPP\Maintenance\cycle_latest.json\`
- Installed release: \`last_deployment.json\`
- Local previous-file backups: \`backups\<release_tag>\notification_inbox.py\`
- Failed releases blocked from automatic retry: \`blocked_releases\<release_tag>\`
- To stop maintenance automation without changing the surveyor watcher:

  \`\`\`powershell
  Disable-ScheduledTask -TaskName 'REPORTAPP Self Maintenance'
  \`\`\`

- To keep diagnostics while preventing deployments, set
  \`auto_deploy\` to \`false\` in the LOCAL policy after disabling the task,
  and then re-enable the task.
- For a manual rollback, disable the **maintenance** task, close the Inbox,
  and restore the desired backup of \`notification_inbox.py\` after verifying
  its origin. Do not delete any \`REPORTAPP_Surveyor_Notifications\` files.
- An unsuccessful **post-install** smoke test performs automatic rollback and
  blocks that release. A damaged GitHub package never reaches the install step.

## Limitations

- GitHub Actions validates Python code on Linux, but the installer and
  Windows Scheduled Task integration require an actual Windows acceptance
  test on the office computer before this can be called fully deployed.
- GitHub Releases are trusted as the delivery control plane; configure
  branch protection, approved reviewers, and release immutability in your
  repository's settings where available. A compromised repository owner
  can publish unsafe Python even if the updater restricts file paths.
- The initial auto-deploy allowlist is **Inbox UI only**. Autonomously
  changing watch criteria, GIS service versions, editing permissions, or
  ArcGIS Pro add-ins is intentionally not authorized.
- If the workstation is offline or the GitHub repository is private,
  release polling may fail safely. Private releases would require an
  approved authenticated downloader, not secrets embedded in source.
- The health report is aggregated; you may need to inspect private
  logs locally to resolve the root cause of an alert.
- The assistant does not have direct remote access to the office computer.
  Optional GitHub issue reporting supplies sanitized signals only; no
  remote execution or automatic AI bug fixing is implied.
