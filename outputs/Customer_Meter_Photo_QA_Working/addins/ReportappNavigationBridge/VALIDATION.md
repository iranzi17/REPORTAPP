# Validation — 2026-10-15

## Build evidence

- Windows host; .NET SDK 10.0.402 targeting **net8.0-windows/x64**.
- Actual Esri package **3.4.0.55405**, supplied in the repository workspace.
- Build.ps1 restore/build succeeded. Final Release build: **0 warnings, 0 errors**.
- Package archive inspected: `Config.daml`, `Install/ReportappNavigationBridge.dll`.
- Final package SHA256:
  `492EBF6845DA06926F1F55502E2903464BFDADD243B86B3E8E74D9DE42B2D5D5` (version 1.0.1).
- Both PowerShell scripts parsed without syntax errors. Install.ps1 was not run;
  Esri RegisterAddIn.exe was invoked directly after the user's installation approval.
- git diff --check passed (only local line-ending normalization notices).

## Python regression evidence

From repository root, with `PYTHONPATH=outputs/Customer_Meter_Photo_QA_Working/src`:

```powershell
python -m pytest outputs/Customer_Meter_Photo_QA_Working/tests --ignore=outputs/Customer_Meter_Photo_QA_Working/tests/test_toolbox_ui.py --ignore=outputs/Customer_Meter_Photo_QA_Working/tests/test_smart_query.py -q
python -m pytest outputs/Customer_Meter_Photo_QA_Working/tests/test_smart_query.py -q
python -m pytest outputs/Customer_Meter_Photo_QA_Working/tests/test_toolbox_ui.py -q
```

- Main run: **266 passed, 99 subtests passed**.
- Smart-query run in separate process: **17 passed, 14 subtests passed**.
- Toolbox UI: **2 failed**, both `ModuleNotFoundError: arcpy`. Requires Pro Python.
- Total available passing tests: **283**, including seven navigation tests.
- Initial unittest discovery ran 271 tests before adding three new tests. Besides
  the two unavailable-arcpy errors, two smart-query assertions failed because
  equal-looking dataclass instances had distinct class identities after toolbox
  module reloads. Isolation resolves those failures; production smart-query code
  was not changed. Unittest misses pytest-style tests in two files, so pytest was
  used for the final regression run above.
- Navigation tests cover exact asset/layer mapping, positive integer validation,
  malformed/untrusted URI rejection without queue writes, atomic distinct requests,
  registry-unavailable behavior, the click CLI, and identical toast body/action URIs.

## Follow-up on the installed Pro 3.4 workstation

Correction: ArcGIS Pro **3.4.0.55405** is installed here, with **MyProject12** open.
The initial detection checked the wrong mapping DLL location. The installed DLL is
under `C:/Program Files/ArcGIS/Pro/bin/Extensions/Mapping`. Pro's Python interpreter
successfully imported arcpy and returned version 3.4. The original regression run
used standalone Python 3.12, which did not have arcpy; its results above remain valid
for that interpreter. Rerunning the two toolbox tests with Pro Python produced
**one pass and one failure**: the test expects 11 QA toolbox tools, but the existing
toolbox contains 12. This is an existing toolbox/test expectation mismatch; this
navigation change does not modify the toolbox. The missing-arcpy limitation is
resolved by using the installed Pro interpreter.

After user approval, Esri RegisterAddIn.exe returned 0, the package was verified
under Documents/ArcGIS/AddIns/ArcGISPro, and the URI handler was registered to
the installed Pro pythonw.exe. MyProject12 was saved and restarted normally.
The module loaded (queue polling and AssemblyCache confirmed). Existing map
connections were verified as datasets 7/10/12 on the exact REG URL in sde.DEFAULT.
The existing layers were reused; no source layer had a definition query.

A read-only unauthenticated query to REG layer 10 returned error **499 Token Required**.
Using installed Pro Python with the map's source connections, read-only source
queries found valid geometry for LV Pole 1, LV Line 1 (ASSETGROUP 9/10), and
Distribution Transformer 1 (ASSETGROUP 12, supported ASSETTYPE). Pole 4422434 was
not returned by a direct source query in the current access/version context.
Its URI was received correctly, failed selection with a diagnostic, and remained
queued until this test request was archived as `.json.missing-feature` to avoid
continual retries. No feature was deleted or edited for the failure test.

Transformer 1 was selected and zoomed to 1:1500, confirmed in the live UI and a
`.done` receipt. Its first navigation attempt was interrupted and retained for
retry; the retry succeeded. Version 1.0.1 now awaits ZoomToSelectedAsync and
ZoomToAsync outside the MCT and uses immediate navigation to avoid animation
interruptions during live map refresh. The rebuilt package again compiled with
zero warnings/errors and was installed before a second normal Pro restart.

Startup/no-active-map retention and retry were observed. Full network outage,
definition-query exclusion, non-default versions and multiple concurrent Pro
processes still need the README's controlled acceptance checks. Real toast
activation remains unverified; invoking the registered URI alone is not treated
as a real Windows toast click.

Version 1.0.1 successfully navigated to LV Line 1 and LV Pole 1 using registered
Windows URIs, with `.done` receipts. The line was visibly highlighted at its extent.
The pole was visibly highlighted at 1:1500 with one selected feature. Its Attributes
pane confirmed Structure Junction / OBJECTID 1 / ASSETGROUP 7 (LV Pole) /
ASSETTYPE 1 (Wooden). No attribute value was changed.

Neither default Python interpreter initially contained winotify. Installed
**winotify 1.1.0** using the Pro interpreter's `pip install --user`; no Pro system
environment package was replaced. A test toast with body/action launch URIs was
submitted successfully. The automation window inventory did not expose a Windows
notification surface, so an actual toast body/action click remains a manual
acceptance step. Mocked body/action wiring and actual registered-URI navigation
are verified separately. No Windows notification/security setting was changed.

No task matching `*REPORTAPP*` was returned by the local scheduled-task lookup.
No task was created, removed or reconfigured. Existing monitoring activation and
surveyor selections were not changed to manufacture a live notification test.

The implementation contains no REG editing calls. No monitor configuration,
SQLite database, surveyor activation timestamp, scheduler task, report or event log
was reset. Pre-existing toolbox XML changes, generated reports and the supplied
SDK package are excluded from the source commit.
