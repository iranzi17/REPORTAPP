# REPORTAPP — Surveyor Activity Notifications (optional)

## Purpose

Existing REPORTAPP alerts report **quality issues only**. A quiet notification
inbox does not establish whether selected surveyors are submitting clean data,
or whether there were no new edits.

This enhancement adds a **separate Windows notification channel** for new
or edited records that pass the configured verified QA checks. It preserves
all existing mandatory-field gap logic, surveyor selections, monitoring dates,
configuration, and flagged-alert history.

## Behavior

- Existing **QA gap** records: keep the original error popup, persistent flag
  inbox and click-to-zoom functionality; no duplicate "clean" popup.
- **No verified QA gaps** in selected surveyors' newly created/edited LV
  Poles, LV Lines or Distribution Transformers: REPORTAPP queues the
  qualifying events and sends **one combined Windows notification at most
  every 30 minutes**, not one for each feature. The digest summarizes counts
  by asset type, creates/edits, and number of surveyors. The individual
  surveyor usernames, OBJECTIDs, edit timestamps and **Zoom in ArcGIS Pro**
  actions are available through **Clean Activity History** in the Inbox.
  A grouped notification has no single OBJECTID to zoom to.
- A clean feature is added to the digest once per source edit timestamp.
  A later edit can enter a subsequent digest. Pending records and the
  30-minute digest clock persist in the existing local SQLite database;
  a failed popup is retried without clearing those records.
- The original watcher polls REG every minute, but sends notifications only
  after the configured 5-minute maturity threshold (typically 5–6 minutes
  after the edit, depending on scheduler timing).
- The activity scanner checks up to 1,000 newly qualifying clean events
  per one-minute cycle; excess events enter the queue on later scans.
  Every successful digest is **one popup**, however many records it summarizes.
- Independently, every 60 minutes after activation, a "watcher healthy" heartbeat summarizes
  the last REG service scan counts, number of selected-user records whose
  latest edit is in the last hour, and QA/clean popup counts for that scan.
  Importantly, 24-hour scan counts **are not today's new submissions**.
- Clean history is stored separately in the existing local SQLite file in
  \`clean_surveyor_activity\`, **not** in \`alert_inbox\`. Quality-alert
  totals and OPEN/REVIEWED statuses remain unchanged.
- The Inbox has a **Clean Activity History** button to view the clean event
  history and queue navigation by OBJECTID.

## Activation on the office computer

After GitHub review/CI and merger to \`main\`, use CMD:

\`\`\`cmd
cd /d "C:\Users\AKIOLI TECHNOLOGY\Desktop\REPORTAPP"
git status --short
git -c gc.auto=0 -c maintenance.auto=false pull --ff-only origin main

set "QA=C:\Users\AKIOLI TECHNOLOGY\Desktop\REPORTAPP\outputs\Customer_Meter_Photo_QA_Working"
set "PY=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
cd /d "%QA%\src"
"%PY%" -m meter_photo_qa.surveyor_notifications --config "%QA%\outputs\REPORTAPP_Surveyor_Notifications\monitor_config.json" --enable-activity --heartbeat-minutes 60
\`\`\`

The --enable-activity command atomically stores a **new, separate activation
timestamp**. The existing watched-user/asset start dates and SQLite
history are preserved. It makes a timestamped backup of \`monitor_config.json\`.
It does **not** auto-notify old clean records.

The existing Windows Task Scheduler task \`REPORTAPP Surveyor Quality Alerts\`
reads the setting during its next scheduled run; no reinstall necessary. The
first heartbeat is due approximately one hour after enablement.

Inspect current monitor statistics after 6–7 minutes:

\`\`\`cmd
powershell -NoProfile -Command "Get-Content '%QA%\outputs\REPORTAPP_Surveyor_Notifications\monitor_config.monitor.log' -Tail 5"
\`\`\`

The Windows log dictionary includes \`clean_notifications_sent\`,
\`clean_notifications_failed\`, \`heartbeat_sent\`, and \`heartbeat_failed\`
alongside the original quality alert and scan metrics.

To inspect clean history without opening the GUI:

\`\`\`cmd
"%PY%" -m meter_photo_qa.surveyor_notifications --config "%QA%\outputs\REPORTAPP_Surveyor_Notifications\monitor_config.json" --list-activity
\`\`\`

To stop **only** the new clean and heartbeat notifications while leaving
quality gap alerts working:

\`\`\`cmd
"%PY%" -m meter_photo_qa.surveyor_notifications --config "%QA%\outputs\REPORTAPP_Surveyor_Notifications\monitor_config.json" --disable-activity
\`\`\`

## Immediate Windows toast acceptance test (no REG queries)

From the same CMD session and folder as above, run:

```cmd
"%PY%" -m meter_photo_qa.surveyor_notifications --config "%QA%\outputs\REPORTAPP_Surveyor_Notifications\monitor_config.json" --send-activity-test --test-asset line --test-objectid 3510143
```

This sends a **TEST** toast only. It does not record clean QA activity, create
fake surveyor events, or claim line 3510143 passes quality checking.
Click **Zoom in ArcGIS Pro (TEST)** to verify navigation to an accessible record.

## Important boundaries

- Read-only REG source; no attribute, geometry, version or network edit.
- No changes to the seven monitored users unless a supervisor separately
  changes the existing Manage Surveyors configuration.
- The self-maintenance updater is **not authorized to auto-deploy changes
  to the live quality watcher**. Production changes require explicit
  local pull after review; no silent service manipulation.
- GitHub CI exercises injected source snapshots and mock toast senders.
  The office machine must complete a live Windows popup and click-to-zoom
  acceptance test to confirm notifications.
- **No gaps found** means no outstanding issues within REPORTAPP's verified
  quality checks. It does not mean the physical installation has been
  inspected or approved by REG.
