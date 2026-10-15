# Validation — 2026-10-15

## Build evidence

- Windows host; .NET SDK 10.0.402 targeting **net8.0-windows/x64**.
- Actual Esri package **3.4.0.55405**, supplied in the repository workspace.
- Build.ps1 restore/build succeeded. Final Release build: **0 warnings, 0 errors**.
- Package archive inspected: `Config.daml`, `Install/ReportappNavigationBridge.dll`.
- Final package SHA256:
  `FF34973C8BAF67692F26070CAB9A13B85C3FD0817602777E98EF90EEE321FD0B`.
- Both PowerShell scripts parsed without syntax errors. Install.ps1 was not run.
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

## Still requires the user's authenticated Pro 3.4 workstation

ArcGIS Pro is absent here. SDK compilation and packaging are verified; installation,
DAML loading, CIM connection representations in the actual REG map, SDK runtime
selection/zoom, Windows foreground activation and real toast activation are not.
No URI protocol or add-in was installed in this environment.

A read-only unauthenticated query to REG layer 10 returned error **499 Token Required**.
The supplied pole 4422434 and real line/transformer IDs were therefore not checked.
Use the README acceptance procedure in the signed-in map. Closed-Pro queue retention,
missing/deleted features, definition queries, authentication/network failures,
non-default versions and multiple Pro processes need runtime acceptance there.

The implementation contains no REG editing calls. No monitor configuration,
SQLite database, surveyor activation timestamp, scheduler task, report or event log
was reset. Pre-existing toolbox XML changes, generated reports and the supplied
SDK package are excluded from the source commit.
