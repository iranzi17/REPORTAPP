# REPORTAPP ArcGIS Pro notification navigation

## v1.0.4 — protect the *source event*, not only the OBJECTID

On 16 October, a notification for POLE OBJECTID **891705** reported
an edit at 16:46 by `ninamenye9683`, while ArcGIS Pro showed the
same OBJECTID/GlobalID with last edit **15 September** by `REGUN_Prod`.
A different REG geodatabase version in the map is a plausible cause;
the screenshots alone do not establish which view is latest. It is
unsafe to navigate to a record using OBJECTID alone when claiming
that it is the specific recently edited feature.

A **new verified alert** now includes the source GlobalID, source
event UTC milliseconds, source actor and GDB version (initially
`sde.DEFAULT`). The link handler validates these values; the
ArcGIS Pro Bridge **v1.0.4** reads the actual map row and verifies all
values **before selecting or zooming**. On disagreement the request
terminates once, the current selection/extent are preserved, and
the details go into `%LOCALAPPDATA%\REPORTAPP\Navigation\bridge-errors.log`.
The bridge also refuses to silently add a default-version REG layer
when the active map has the same source layer on a different version.
The source event time describes the watcher FeatureServer version,
not necessarily the displayed map's branch version.

**Old notification links with no source-edit context are deliberately
rejected by v1.0.4**, so the user is never navigated by an
unverified older alert. To find a feature by OBJECTID for exploration,
use the explicit **Find Asset** form, which queues a separately
marked manual action (no claim about the edited date).
New verified alerts, manual find, Inbox history and Clean Activity
History require the updated Python `alert_navigation.py` and
`notification_inbox.py` from the same source revision as bridge v1.0.4.

Do **not** install the new add-in against stale office Python code:
first sync REPORTAPP source safely, then close ArcGIS Pro, install
`ReportappNavigationBridge.esriAddInX` from the tested
`reportapp-bridge-v1.0.4` release, and reopen Pro.
These operations do not edit source REG data or QA history.



## Critical safety change in v1.0.3

A reported office issue showed ArcGIS Pro jumping back to an older pole or
line **minutes after** the supervisor clicked another notification. The v1.0.2
bridge retried failed requests every minute for up to 24 hours; old requests
could later execute successfully, hijacking the current map. This version
**does not retry any request**. Every click is attempted once and expires
after **15 seconds**. When several requests exist, the newest click takes
priority and older ones are marked `.superseded`. A failed request is moved
to `.failed`, not retried. The bridge checks again before selection and
before zooming that the request is still fresh, that the active map did not
change, and that navigation was not paused.

REPORTAPP's Inbox now exposes **Pause Map Zoom / Resume Map Zoom**.
Pausing sets `%LOCALAPPDATA%\REPORTAPP\Navigation\navigation-paused.flag`
and renames any pending `*.json` to `*.json.paused` without deleting
history. Resuming allows only fresh new explicit requests; no paused
file is replayed. Pausing while a v1.0.2 add-in is already performing a
slow query may not stop that one operation: restart Pro at your next safe
break and install the rebuilt v1.0.3 add-in for full protection.

**Installation is separate from Python/watcher maintenance** because the
current safe updater is not authorized to install `.esriAddInX` packages.
For a no-CMD upgrade, download
`ReportappNavigationBridge.esriAddInX` from the verified
`reportapp-bridge-v1.0.3` GitHub release, close ArcGIS Pro,
double-click the package and accept the Esri installer, then reopen Pro.
Use the Inbox **Pause Map Zoom** until you finish installation.

The source event time on a surveyor notification describes when REG recorded
the asset edit; it is **not** the time that Zoom was clicked or queued.



Targets **ArcGIS Pro 3.4 / .NET 8 / Windows x64**. Release compilation against
Esri.ArcGISPro.Extensions30 **3.4.0.55405** succeeded with zero warnings/errors
on 2026-10-15. Package: `bin/Release/net8.0-windows/ReportappNavigationBridge.esriAddInX`.
Follow-up inspection confirmed
ArcGIS Pro **3.4.0.55405** is installed and running with MyProject12 open. The initial
absence report was incorrect: the mapping DLL lives under bin/Extensions/Mapping.
The add-in and URI handler are now installed. Live tests in MyProject12 succeeded
for Transformer 1, LV Line 1 and LV Pole 1. The pole's Attributes pane confirms
OBJECTID 1 / LV Pole / Wooden at 1:1500. See VALIDATION.md for remaining checks.

## Build

Open PowerShell in this directory:

```powershell
.\Build.ps1
# Optional: directory containing the supplied Esri .nupkg
.\Build.ps1 -LocalPackageSource 'G:\Other computers\My computer\REPORTAPP'
```

Install the [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0) if needed.
Visual Studio is optional for building. For debugging, install Visual Studio 2022
with .NET desktop development and the ArcGIS Pro SDK 3.4 extension, then open
`ReportappNavigationBridge.csproj`.

The project pins Esri 3.4 assemblies and targets net8.0-windows/x64 with WPF.
Packaging uses the Esri layout: Config.daml at archive root, DLL under Install/.
It excludes Esri's legacy CodeTaskFactory build targets, which need full-framework
MSBuild, and uses MSBuild ZipDirectory. Building does not install/unregister an
add-in. No SDK assemblies are included in the package.

## Install and register

1. Save your project and close Pro 3.4.
2. Run `.\Install.ps1`, or double-click the package, and finish the Esri installer.
   The script opens the interactive installer; it does not assert success.
3. Restart Pro and verify REPORTAPP in **Project > Add-In Manager**.
4. Register the click handler from this folder using standalone Python:

```powershell
$python = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
& $python "$PWD/../../src/meter_photo_qa/alert_navigation.py" --register
& $python "$PWD/../../src/meter_photo_qa/alert_navigation.py" --status
```

Use this computer's actual paths. Registration is per Windows user, needs no
administrator and must be repeated after moving Python or REPORTAPP. The monitor's
Python environment must still have winotify. No scheduler/configuration/database,
surveyor selection, activation time, report or event log is replaced by these scripts.
On this workstation, winotify 1.1.0 was installed for the current user of Pro Python.

## Behavior

Toast body and **Zoom in ArcGIS Pro** action use the same validated URI. The inbox
also has a zoom button for saved alerts; it queues directly without changing notes
or status. Only pole/12, line/10, transformer/7 and positive signed 64-bit OBJECTIDs
are accepted. No GlobalID lookup is used. Python atomically queues under
`%LOCALAPPDATA%/REPORTAPP/Navigation/Requests`; it never launches Pro or a shell.

The auto-loaded module polls every two seconds. A per-session user mutex permits
one Pro process to consume requests; use one Pro process for predictable map choice.
It verifies the exact REG FeatureServer URL, numeric dataset and exposed version
from the CIM connection and service connector. Local geodatabases and similarly
named services are rejected. Unrecognized connection representations are not guessed.
If no verified layer is found, it adds only the hardcoded REG sublayer to the active
map. This can change the unsaved map, but never edits feature data. The service
default is used for new layers and the connector is checked before selection.
Non-default versions are not changed automatically. Multiple verified matching layers
produce a diagnostic instead of an arbitrary selection.

Definition queries are respected. Filtered/deleted features stay queued. Unrelated
selections are cleared after finding the requested record so zoom targets only that
feature. The layer becomes visible; parent-group visibility, scale visibility and
access restrictions may still need adjustment in Pro. Lines use the selection extent;
points in 2D maps use 1:1500. Selection remains available for inspection. The Pro
window is activated after success, subject to Windows foreground restrictions.
An active map is required; a layout-only view is insufficient.

**v1.0.3:** Each click is one-shot and expires after 15 seconds. No minute-later
retry is permitted. Newer clicks supersede earlier pending requests. Success
receipts end in `.json.done`, failed one-shot requests in `.json.failed`,
invalid or expired requests in `.json.invalid`, superseded requests in
`.json.superseded`, and operator-paused requests in `.json.paused`. Older
receipt/log files are retained for audit but never replayed.

Diagnostics: `%LOCALAPPDATA%/REPORTAPP/Navigation/bridge-errors.log` and
`navigation-errors.log`. Missing authentication, missing features, wrong versions,
no active map and definition-query exclusions require user correction in Pro.

## Find Asset in the Quality Notification Inbox

The Inbox includes a separate **Find Asset** control for **LV Pole, LV Line,
and Transformer**. Enter the REG source OBJECTID and click
**Find & Zoom in ArcGIS Pro**. This works without a corresponding QA alert:
the request goes into the existing validated local navigation queue and
the active Pro 3.4 bridge checks the matching FeatureServer sublayer.

The control reports **queued**, not successful, until ArcGIS Pro actually
selects the source feature. The source must be available in the active map's
authorized version and pass layer filtering. This does not insert alerts,
change the alert search/list/counts, alter review notes, change monitoring
configuration, or edit REG features. The Python Inbox must be restarted
after pulling updated source. The existing installed 1.0.2 add-in can handle
the request; no C# rebuild is needed for the Find Asset control.

## Selection-safety correction (requires rebuild)

A live office test on 2026-10-16 found that failed navigation requests
cleared manual map selections every minute. The source now performs a
read-only `FeatureLayer.Search` preflight and a non-destructive
`SelectionCombinationMethod.Add` check before clearing unrelated
selections for a **confirmed** successful navigation target. This source
change is not active in an already installed .esriAddInX until rebuilt,
installed, and Pro restarted. Keep failed requests renamed
`*.json.paused` until the replacement build is deployed; do not purge
inbox/monitoring history. The C# change needs on-machine SDK compilation
and a live missing-record/manual-selection regression test.

## Safe acceptance test in authenticated Pro 3.4

1. Sign in normally to REG. Open a disposable 2D project/map in sde.DEFAULT.
   Record current selections if you need them later.
2. Open `reportapp://zoom/pole/4422434` through Windows Run.
3. Confirm the exact REG Structure Junction layer **12**, OBJECTID **4422434**,
   sole selected feature, 1:1500 zoom, inspectable attributes and a `.done` receipt.
4. Test a real toast body and its action separately, then a saved inbox alert.
5. Obtain real LV Line and Distribution Transformer OBJECTIDs from an authenticated
   map or existing inbox, verifying the exact source layer first. Test
   `reportapp://zoom/line/<actual-id>` and `reportapp://zoom/transformer/<actual-id>`.
   Do not substitute invented IDs. Read-only queries using the installed Pro Python
   verified valid geometry for LV Line **1**, Distribution Transformer **1**, and
   LV Pole **1** in this map's source. Pole **4422434** was not returned by a direct
   source query in the current access/version context; the layer has no definition
   query. Its failed test request was retained as `.json.missing-feature` for diagnosis.
6. Close Pro, enqueue a URL, confirm the JSON persists, then reopen with a map
   within 24 hours. No extra Pro instance should be launched by a click.
7. Query an ID and confirm it has no record before using it for the missing-feature
   test. Do not delete a feature for testing. Confirm diagnostics and retained queue.
8. Disconnect this workstation's network temporarily, enqueue a valid request,
   confirm diagnostics/retention, restore access and verify retry.
9. In a disposable project, test a definition query excluding the feature, a
   non-default layer version, no active map, a similarly named foreign layer,
   duplicate matching layers and expired/malformed queue files. Expect diagnostics
   or addition of the trusted REG layer; never a GlobalID fallback or GIS edits.

## Uninstall

Remove REPORTAPP in Pro's Add-In Manager and restart Pro. To stop URI handling,
use Registry Editor at `HKEY_CURRENT_USER/Software/Classes/reportapp`, verify the
open command points to this repository's alert_navigation.py, and remove only that
protocol key. Keep Navigation data unless you intend to discard pending clicks and
diagnostics. The scheduled monitor and inbox continue independently.

## References and validation

See VALIDATION.md for actual checks and outstanding local acceptance work.
SDK references: [Esri NuGet guide](https://github.com/Esri/arcgis-pro-sdk/wiki/ProGuide-ArcGIS-Pro-Extensions-NuGet),
[3.4 service connection API](https://pro.arcgis.com/en/pro-app/3.4/sdk/api-reference/topic7647.html),
[3.4 selection zoom API](https://pro.arcgis.com/en/pro-app/3.4/sdk/api-reference/topic12028.html).
