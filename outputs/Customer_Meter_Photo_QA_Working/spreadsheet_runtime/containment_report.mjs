import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("Usage: containment_report.mjs input.json output.xlsx [preview-dir]");
}

if (inputPath === "--inspect-xlsx") {
  const input = await FileBlob.load(outputPath);
  const checkedWorkbook = await SpreadsheetFile.importXlsx(input);
  const checkedPreviewDir = previewDir;
  if (!checkedPreviewDir) {
    throw new Error("Inspection mode requires a preview directory");
  }
  await fs.mkdir(checkedPreviewDir, { recursive: true });
  for (const sheetName of ["Summary", "Containment", "Missing Rules"]) {
    const rendered = await checkedWorkbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1.2,
      format: "png",
    });
    const fileName = sheetName.toLowerCase().replaceAll(" ", "_") + ".png";
    await fs.writeFile(
      `${checkedPreviewDir}/${fileName}`,
      new Uint8Array(await rendered.arrayBuffer()),
    );
  }
  const inspection = await checkedWorkbook.inspect({
    kind: "table",
    range: "Summary!A1:J26",
    include: "values,formulas",
    tableMaxRows: 26,
    tableMaxCols: 10,
  });
  const errors = await checkedWorkbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  const globalIds = await checkedWorkbook.inspect({
    kind: "match",
    searchTerm: "GLOBALID|Global ID|globalid",
    options: { useRegex: true, maxResults: 100 },
    summary: "Global ID scan",
  });
  console.log(
    JSON.stringify({
      inspection: inspection.ndjson,
      errors: errors.ndjson,
      globalIds: globalIds.ndjson,
    }),
  );
}

if (inputPath !== "--inspect-xlsx") {
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const containment = workbook.worksheets.add("Containment");
const missing = workbook.worksheets.add("Missing Rules");

const COLORS = {
  dark: "#1F4E3D",
  mid: "#D9EAD3",
  light: "#F3F7F4",
  blue: "#D9E7F5",
  amber: "#FFF2CC",
  red: "#F4CCCC",
  grey: "#E7E6E6",
  border: "#B7C4BC",
  text: "#1F1F1F",
};

function titleBand(sheet, endColumn, title, subtitle) {
  sheet.getRange(`A1:${endColumn}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${endColumn}1`).format = {
    fill: COLORS.dark,
    font: { bold: true, color: "#FFFFFF", size: 15 },
    verticalAlignment: "center",
  };
  sheet.getRange(`A1:${endColumn}1`).format.rowHeight = 28;

  sheet.getRange(`A2:${endColumn}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endColumn}2`).format = {
    fill: COLORS.light,
    font: { color: "#45564D", italic: true, size: 10 },
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${endColumn}2`).format.rowHeight = 22;
}

function headerStyle(range) {
  range.format = {
    fill: COLORS.mid,
    font: { bold: true, color: COLORS.text },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
  range.format.rowHeight = 30;
}

function bodyStyle(range) {
  range.format = {
    font: { color: COLORS.text, size: 10 },
    verticalAlignment: "top",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "thin", color: "#E2E8E4" },
      bottom: { style: "thin", color: COLORS.border },
    },
  };
}

function statusRules(range) {
  range.conditionalFormats.add("containsText", {
    text: "EXISTING",
    format: { fill: "#E2F0D9", font: { color: "#375623" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "APPLIED",
    format: { fill: "#DDEBF7", font: { color: "#1F4E79" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "PROPOSE",
    format: { fill: COLORS.amber, font: { color: "#7F6000" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "REVIEW",
    format: { fill: "#FCE4D6", font: { color: "#843C0C" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "CONFLICT",
    format: { fill: COLORS.red, font: { color: "#9C0006" } },
  });
}

// Summary sheet
summary.showGridLines = false;
titleBand(
  summary,
  "H",
  "Substation Containment Report",
  `${payload.area} | ${payload.operation}`,
);

summary.getRange("A4:B8").values = [
  ["Report area", payload.area],
  ["Operation", payload.operation],
  ["Utility network version", payload.version],
  ["Generated", payload.generatedAt],
  ["Substations", payload.substations.join(", ") || "None"],
];
summary.getRange("A4:A8").format = {
  fill: COLORS.light,
  font: { bold: true, color: COLORS.dark },
};
summary.getRange("A4:B8").format.borders = {
  preset: "outside",
  style: "thin",
  color: COLORS.border,
};
summary.getRange("A4:B8").format.wrapText = true;

summary.getRange("A10:J10").values = [[
  "Substations",
  "Bays",
  "Devices in Bays",
  "Association Rows",
  "Existing",
  "Applied",
  "Proposed",
  "Review / Conflict",
  "Missing Rules",
  "Failed",
]];
headerStyle(summary.getRange("A10:J10"));

const containmentEnd = Math.max(3, payload.containmentRows.length + 3);
const missingEnd = Math.max(3, payload.missingRuleRows.length + 3);
summary.getRange("A11:J11").formulas = [[
  "=COUNTA(A15:A500)",
  `=COUNTIF('Containment'!$C$4:$C$${containmentEnd},\"Substation > Bay\")`,
  `=COUNTIF('Containment'!$C$4:$C$${containmentEnd},\"Bay > Device\")+COUNTA('Missing Rules'!$A$4:$A$${missingEnd})`,
  `=COUNTA('Containment'!$A$4:$A$${containmentEnd})`,
  `=COUNTIF('Containment'!$I$4:$I$${containmentEnd},\"EXISTING\")`,
  `=COUNTIF('Containment'!$I$4:$I$${containmentEnd},\"APPLIED\")`,
  `=COUNTIF('Containment'!$I$4:$I$${containmentEnd},\"PROPOSE\")`,
  `=COUNTIF('Containment'!$I$4:$I$${containmentEnd},\"REVIEW\")+COUNTIF('Containment'!$I$4:$I$${containmentEnd},\"CONFLICT\")`,
  `=COUNTA('Missing Rules'!$A$4:$A$${missingEnd})`,
  `=COUNTIF('Containment'!$I$4:$I$${containmentEnd},\"FAILED\")`,
]];
summary.getRange("A11:J11").format = {
  fill: "#FFFFFF",
  font: { bold: true, color: COLORS.dark, size: 12 },
  horizontalAlignment: "center",
  borders: { preset: "all", style: "thin", color: COLORS.border },
};
summary.getRange("A11:J11").format.numberFormat = "#,##0";
summary.getRange("A11:J11").format.rowHeight = 26;

summary.getRange("A14:H14").values = [[
  "Substation",
  "Bays",
  "Devices in Bays",
  "Existing",
  "Applied",
  "Proposed",
  "Review / Conflict",
  "Missing Rules",
]];
headerStyle(summary.getRange("A14:H14"));

if (payload.substations.length) {
  const substationStart = 15;
  const substationEnd = substationStart + payload.substations.length - 1;
  summary.getRange(`A${substationStart}:A${substationEnd}`).values =
    payload.substations.map((name) => [name]);
  for (let row = substationStart; row <= substationEnd; row += 1) {
    summary.getRange(`B${row}:H${row}`).formulas = [[
      `=COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$C$4:$C$${containmentEnd},\"Substation > Bay\")`,
      `=COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$C$4:$C$${containmentEnd},\"Bay > Device\")+COUNTIF('Missing Rules'!$B$4:$B$${missingEnd},$A${row})`,
      `=COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$I$4:$I$${containmentEnd},\"EXISTING\")`,
      `=COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$I$4:$I$${containmentEnd},\"APPLIED\")`,
      `=COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$I$4:$I$${containmentEnd},\"PROPOSE\")`,
      `=COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$I$4:$I$${containmentEnd},\"REVIEW\")+COUNTIFS('Containment'!$B$4:$B$${containmentEnd},$A${row},'Containment'!$I$4:$I$${containmentEnd},\"CONFLICT\")`,
      `=COUNTIF('Missing Rules'!$B$4:$B$${missingEnd},$A${row})`,
    ]];
  }
  bodyStyle(summary.getRange(`A${substationStart}:H${substationEnd}`));
  summary.getRange(`B${substationStart}:H${substationEnd}`).format.numberFormat = "#,##0";
  const summaryTable = summary.tables.add(`A14:H${substationEnd}`, true, "SubstationSummaryTable");
  summaryTable.style = "TableStyleMedium4";
}

summary.freezePanes.freezeRows(2);
summary.getRange("A1:J40").format.font.name = "Aptos";
summary.getRange("A:A").format.columnWidth = 22;
summary.getRange("B:B").format.columnWidth = 38;
summary.getRange("C:J").format.columnWidth = 16;

// Containment detail sheet
containment.showGridLines = false;
titleBand(
  containment,
  "J",
  "Containment Details",
  "Human-readable operational records for the selected substations.",
);
const containmentHeaders = [
  "No.",
  "Substation",
  "Association Level",
  "Bay",
  "Record ID",
  "Asset ID",
  "Asset Group",
  "Asset Type",
  "Status",
  "Assessment",
];
containment.getRange("A3:J3").values = [containmentHeaders];
headerStyle(containment.getRange("A3:J3"));
if (payload.containmentRows.length) {
  containment.getRange(`A4:J${payload.containmentRows.length + 3}`).values =
    payload.containmentRows.map((row) => containmentHeaders.map((header) => row[header] ?? ""));
  bodyStyle(containment.getRange(`A4:J${payload.containmentRows.length + 3}`));
  containment.getRange(`A4:A${payload.containmentRows.length + 3}`).format.numberFormat = "#,##0";
  containment.getRange(`E4:E${payload.containmentRows.length + 3}`).format.numberFormat = "0";
  statusRules(containment.getRange(`I4:I${payload.containmentRows.length + 3}`));
  const containmentTable = containment.tables.add(
    `A3:J${payload.containmentRows.length + 3}`,
    true,
    "ContainmentDetailsTable",
  );
  containmentTable.style = "TableStyleMedium4";
}
containment.freezePanes.freezeRows(3);
containment.getRange(`A1:J${Math.max(6, containmentEnd + 1)}`).format.font.name = "Aptos";
const containmentWidths = [7, 20, 21, 28, 12, 20, 24, 28, 13, 48];
containmentWidths.forEach((width, index) => {
  containment.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width;
});

// Missing-rule side report
missing.showGridLines = false;
titleBand(
  missing,
  "J",
  "Equipment Missing Containment Rules",
  "Excluded from the containment operation. Configure the listed rule before inclusion.",
);
const missingHeaders = [
  "No.",
  "Substation",
  "Bay",
  "Bay Type",
  "Equipment Record ID",
  "Asset ID",
  "Equipment Group",
  "Equipment Type",
  "Spatial Bay Count",
  "Required Rule",
];
missing.getRange("A3:J3").values = [missingHeaders];
headerStyle(missing.getRange("A3:J3"));
if (payload.missingRuleRows.length) {
  missing.getRange(`A4:J${payload.missingRuleRows.length + 3}`).values =
    payload.missingRuleRows.map((row) => missingHeaders.map((header) => row[header] ?? ""));
  bodyStyle(missing.getRange(`A4:J${payload.missingRuleRows.length + 3}`));
  missing.getRange(`A4:A${payload.missingRuleRows.length + 3}`).format.numberFormat = "#,##0";
  missing.getRange(`E4:E${payload.missingRuleRows.length + 3}`).format.numberFormat = "0";
  missing.getRange(`I4:I${payload.missingRuleRows.length + 3}`).format.numberFormat = "#,##0";
  missing.getRange(`A4:J${payload.missingRuleRows.length + 3}`).conditionalFormats.add(
    "expression",
    {
      formula: "=$I4>1",
      format: { fill: COLORS.amber },
    },
  );
  const missingTable = missing.tables.add(
    `A3:J${payload.missingRuleRows.length + 3}`,
    true,
    "MissingRulesTable",
  );
  missingTable.style = "TableStyleMedium4";
}
missing.freezePanes.freezeRows(3);
missing.getRange(`A1:J${Math.max(6, missingEnd + 1)}`).format.font.name = "Aptos";
const missingWidths = [7, 20, 30, 24, 18, 20, 24, 30, 17, 58];
missingWidths.forEach((width, index) => {
  missing.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width;
});

const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);

if (previewDir) {
  await fs.mkdir(previewDir, { recursive: true });
  for (const sheetName of ["Summary", "Containment", "Missing Rules"]) {
    const rendered = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1.2,
      format: "png",
    });
    const fileName = sheetName.toLowerCase().replaceAll(" ", "_") + ".png";
    await fs.writeFile(
      `${previewDir}/${fileName}`,
      new Uint8Array(await rendered.arrayBuffer()),
    );
  }
  const inspection = await workbook.inspect({
    kind: "table",
    range: "Summary!A1:J26",
    include: "values,formulas",
    tableMaxRows: 26,
    tableMaxCols: 10,
  });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  console.log(JSON.stringify({ inspection: inspection.ndjson, errors: errors.ndjson }));
}
}
