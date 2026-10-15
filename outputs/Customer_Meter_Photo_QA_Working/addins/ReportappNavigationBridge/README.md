# REPORTAPP — clickable ArcGIS Pro notifications (SDK bridge)

**Status: SDK source prototype. NOT compiled or installed on the user's machine.**
The existing Task Scheduler monitor remains unchanged.

## Why this is a separate add-in

The desktop watcher runs outside the ArcGIS Pro application, so it cannot use
`arcpy.mp.ArcGISProject("CURRENT")` to manipulate a currently open map.
An ArcGIS Pro SDK/.NET add-in must be running inside ArcGIS Pro to receive a
click and safely select/zoom a feature using `QueuedTask.Run`.

## Link mechanism (no remote calls)

1. The desktop notification uses the local `reportapp://zoom?asset=pole&objectid=4422434` URL.
2. On an **explicit** installation command, a per-user `HKCU\Software\Classes\reportapp`
   scheme is registered, pointing to the REPORTAPP Python click handler.
3. The click handler validates the asset/OBJECTID and atomically writes a small
   JSON request to `%LOCALAPPDATA%\REPORTAPP\Navigation\Requests`.
4. The ArcGIS Pro add-in reads the request, finds the expected REG
   FeatureServer sublayer (12 poles, 10 LV lines, 7 transformers), selects
   the specific `OBJECTID` and zooms to it. If absent, it attempts to add
   the exact trusted source layer to the current map.
5. If the map or source is unavailable, the request remains; the add-in
   never modifies any REG feature, never deletes the monitoring database,
   and does not create a second ArcGIS Pro instance.

## One-time add-in build (requires matching Pro SDK)

1. In ArcGIS Pro, check **About ArcGIS Pro** and note the full 3.x version.
2. Install Visual Studio 2022 + .NET 8 SDK + matching Esri ArcGIS Pro SDK for .NET.
   Esri's `ArcGIS Pro Module Add-in` project template includes the Pro
   references, DAML packaging and build configuration.
3. Create a **Module Add-in** project named `ReportappNavigationBridge`.
   Use the SDK wizard matched to the installed ArcGIS Pro release.
4. Replace the generated module class with `BridgeModule.cs`, retaining the
   SDK-generated project references. The module's namespace must be
   `ReportappNavigationBridge`.
5. In the template-generated `Config.daml`, set module `className`
   to `BridgeModule` and `autoLoad="true"` (see the reference
   `Config.daml`). Preserve the correct `desktopVersion` and framework
   settings from the generated template. Keep any SDK-required packaging files.
6. Compile in Visual Studio and install the resulting `.esriAddInX` by
   double-clicking it. Reopen ArcGIS Pro with a 2D map.
7. After that, and **only after** installing the add-in, register the
   `reportapp://` handler for the current Windows user:
   ```cmd
   cd /d "C:\Users\AKIOLI TECHNOLOGY\Desktop\REPORTAPP\outputs\Customer_Meter_Photo_QA_Working\src"
   "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" -m meter_photo_qa.alert_navigation --register
   "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" -m meter_photo_qa.alert_navigation --status
   ```
8. Test safely with a known existing record (does not edit REG):
   `start "" "reportapp://zoom?asset=pole&objectid=4422434"`.
   Windows may ask once for permission to open REPORTAPP links.
9. Check failures in
   `%LOCALAPPDATA%\REPORTAPP\Navigation\bridge-errors.log`.
   Do not register the handler before the Pro bridge has been installed and tested.

## Important limitations

- The C# sample is provided as source and **has not been compiled or verified
  against the user's exact ArcGIS Pro release**.
- The **open current map** must have access to the REG service and permission
  to view the record. Definition queries and feature-level access restrictions
  can prevent selection. A different version may return different features.
- This prototype currently finds layers by exact REST source URL. Existing
  Utility Network sublayers may expose different `GetPath()` URIs and
  require a verified service-connection source resolver.
- The add-in may add a read-only feature service layer to the active map.
  It does not edit GIS feature data but may change the unsaved map display.
- Existing alert history remains intact; only newly generated desktop
  notifications after URI registration become clickable. The inbox stays
  independently available.
- Avoid publishing REG account details, session tokens or source data in
  the URL handler or click request.
