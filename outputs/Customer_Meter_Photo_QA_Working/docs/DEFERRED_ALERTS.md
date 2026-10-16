# Deferred Previous-Day QA Notifications (Rwanda)

## Behavior
- Today's (Kigali local calendar date, UTC+02) **new qualifying QA gaps**
  continue to be delivered after the existing five-minute maturity interval.
- A record whose latest source CREATE/EDIT date is **yesterday or earlier**
  and has an outstanding QA issue is put in the local SQLite
  `delayed_qa_notifications` queue rather than interrupting the surveyors
  while they're on site.
- If the crew are **off site**, queued historical notifications are delivered
  in batches of up to 5 per scheduled watcher scan. Existing zoom action works.
- The queue survives restarts and the moving 24-hour source query window.
  If the source feature is visible in the newest scan and no longer flagged,
  its obsolete delayed notification is discarded.
- The existing flag Inbox, open/reviewed status, selected seven surveyors,
  source feature service, and surveyor monitoring activation clock are not reset.
- **No writes** to REG GIS data or any feature geometry.
- The feature defaults to `on_site` until you set a confirmed schedule or
  explicitly select `off_site`. No guessed hours or site attendance.
- Clean/no-gap live activity notifications are still handled by their separate
  once-per-source-event system, and heartbeat alerts continue.

## Set site status without commands

In the REPORTAPP Quality Notification Inbox click **Site Status**:
- **Surveyors are on site**: hold previous-day QA alerts; today's notifications
  still arrive in normal time.
- **Surveyors have left**: release stored previous-day notifications.
- **Automatic**: choose the regular working days and start/end time in
  *Rwanda local time (UTC+02)*. The mode is evaluated on each scan.
  Work hours are validated and never guessed.

Changes to `monitor_config.json` are atomic and a timestamped backup
is created. The watcher reads the changes on its next one-minute run.

## Deployment / local updater boundary

This is **live watcher code** (not only GUI), so the first installation cannot
happen through the previously installed Self Maintenance v1 updater: that
version deliberately permits only `notification_inbox.py`. Never claim the
workstation has received this code until a separate approved bootstrap is
installed. Automatic deployment of a broader allowlist requires an explicit
maintainer upgrade, tested safeguards, and a signed/hash-verified GitHub release
with rollback; enabling the upgrade is a distinct step.

## Limits / reality check

- "On site" cannot be inferred reliably from the last feature edit.
  Use supervisor-set mode or the agreed work schedule.
- Prior Windows notifications already displayed or recorded in the Inbox
  will not be retroactively delayed.
- Source edits older than the monitor's 24-hour acquisition window that
  were never seen cannot be reconstructed from this queue.
- A previously queued historical alert that ages out of source scope is
  labeled retrospective; recheck the current source before taking corrective
  action when possible.
