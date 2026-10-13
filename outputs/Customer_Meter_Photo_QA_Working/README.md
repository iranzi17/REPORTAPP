# Customer Meter Photo QA working folder

This is the working copy of the ArcGIS Pro Python toolbox from `Desktop/UN Model/Customer_Meter_Photo_QA`. The original folder is preserved. Open `CustomerMeterPhotoQA.pyt` in ArcGIS Pro for **Watch LV Line Data Quality**, survey reporting, and meter-photo preflight checks. Open `CustomerMeterPhotoQA_Operations.pyt` separately for the two utility-network Preview / Apply tools.

The folder contains the toolbox, its Python helpers in `src`, geographic selectors and quality rules in `config`, report builders in `spreadsheet_runtime`, scripts, and focused tests. Generated workbooks belong in `outputs` and are created there by default.

The drawing layer in `config/custom_boundary_template.lyrx` points to the shapefile in this working folder. `spreadsheet_runtime/node_modules` links to the shared local dependency library used by the substation and relay workbook builders; it does not store another copy of that library.

To use it in ArcGIS Pro, add this folder as a folder connection in the Catalog pane, then open the toolbox you need. If the old toolbox is already connected, remove that folder connection or select the new toolbox explicitly before running a tool. Refresh the new toolbox in Catalog if ArcGIS Pro still shows its previous tool list.

The LV line watcher rules are in `config/lv_line_quality_rules.json`. **Transformer Name is mandatory**, independently of the percentage score. `MEETS_THRESHOLD` means the line passed these completeness checks; it is not final approval of the data. The rules file supplies the default percentage. The tool checks required service fields and coded domains before scoring so a changed service schema produces a clear error.

The watcher's District list includes all 30 Rwanda districts. Leave District blank to check **all districts and sectors**. Choose one district and leave Sector(s) blank to check every sector in that district. A drawn polygon overrides the administrative selection. The selected dates include lines created **or last edited** within the period, including lines without a creator username when no surveyor filter is selected.

Every run writes a new Excel report in `outputs` and, when selected, a new flagged-line feature class in the current project's geodatabase. Their names contain the **local date and time of the actual run** as `YYYYMMDD_HHMMSS`; a same-second collision gets an additional number. Prior outputs are preserved.

The **Review Queue** sheet carries flagged lines and reviewer decisions between reports. Edit the yellow columns for Review Status, Assigned To, Reviewed By, Reviewed At UTC, and Resolution Notes, then save the workbook. The next run automatically imports the most recent timestamped watcher report in the same output folder. Use **Previous QA report** under Advanced to choose a different workbook. A line flagged again after `RESOLVED` or `DISMISSED` is marked `REOPENED`. A line outside the current run stays in the queue as `NOT_CHECKED`; it is not treated as cleared.

The watcher reads the source feature service without editing it. The separate Operations toolbox defaults to Preview and can apply approved utility-network association proposals when explicitly selected.

The survey progress report starts with distribution-transformer points inside the selected boundary. For each point it runs a read-only **Connected utility-network trace** with consistency validation and uses the distinct connected LV feature IDs as membership. The selected dates and surveyors are applied afterward, so an older connected line is not counted as work completed during the chosen period. Transformer points remain separate even when they share a name.

The **Transformer Tracking Log** records the trace evidence and boundary continuation. If one LV line is reached from multiple localized transformers, or a trace reaches multiple transformer points, that assignment is excluded from totals and placed under **Unassigned LV Candidates** for review. Connected lines remain countable when their recorded Transformer Name is blank or different; they appear in **Connected Name Review** so the attribute can be corrected. The report measures connectivity, not energized state or switch traversability.

This working folder excludes the FieldGuard app, sample meter photos, OCR trial results, prior generated reports, caches, and backup toolbox files. The original folder still contains all of them.
