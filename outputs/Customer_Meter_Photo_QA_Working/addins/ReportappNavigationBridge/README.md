# REPORTAPP ArcGIS Pro notification navigation

Targets **ArcGIS Pro 3.4 / .NET 8 / Windows x64**. Release compilation against
Esri.ArcGISPro.Extensions30 **3.4.0.55405** succeeded with zero warnings/errors
on 2026-10-15. Package: `bin/Release/net8.0-windows/ReportappNavigationBridge.esriAddInX`.
**Installation and live navigation remain unverified:** this computer has no Pro.

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

Failures retry once per minute, allowing other requests to proceed. Requests expire
after 24 hours. Success receipts end in `.json.done`, rejected requests in
`.json.invalid`, and requests expiring during retries in `.json.expired` (already
expired when first read are invalid). Receipts prevent normal replay. A crash between
selection and receipt can repeat the harmless selection after restart. Receipts and
logs are retained for manual archival; they are not automatically deleted.

Diagnostics: `%LOCALAPPDATA%/REPORTAPP/Navigation/bridge-errors.log` and
`navigation-errors.log`. Missing authentication, missing features, wrong versions,
no active map and definition-query exclusions require user correction in Pro.

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
   Do not substitute invented IDs. Unauthenticated REG access returned **499 Token
   Required** here; neither these IDs nor the supplied pole could be verified.
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
