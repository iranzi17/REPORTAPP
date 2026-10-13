import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("Usage: relay_association_report.mjs input.json output.xlsx [preview-dir]");
}

if (inputPath === "--inspect-xlsx") {
  if (!previewDir) throw new Error("Inspection mode requires a preview directory");
  const input = await FileBlob.load(outputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  await fs.mkdir(previewDir, { recursive: true });
  for (const sheetName of ["Summary", "Relay Associations", "Exceptions"]) {
    const rendered = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1.2,
      format: "png",
    });
    await fs.writeFile(
      `${previewDir}/${sheetName.toLowerCase().replaceAll(" ", "_")}.png`,
      new Uint8Array(await rendered.arrayBuffer()),
    );
  }
  const inspection = await workbook.inspect({
    kind: "table",
    range: "Summary!A1:H30",
    include: "values,formulas",
    tableMaxRows: 30,
    tableMaxCols: 8,
  });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  const globalIds = await workbook.inspect({
    kind: "match",
    searchTerm: "GLOBALID|Global ID|globalid",
    options: { useRegex: true, maxResults: 100 },
    summary: "Global ID scan",
  });
  console.log(JSON.stringify({
    inspection: inspection.ndjson,
    errors: errors.ndjson,
    globalIds: globalIds.ndjson,
  }));
  process.exit(0);
}

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const details = workbook.worksheets.add("Relay Associations");
const exceptions = workbook.worksheets.add("Exceptions");

const COLORS = {
  dark: "#244A3B",
  mid: "#DCE9E2",
  light: "#F4F7F5",
  amber: "#FFF2CC",
  red: "#F4CCCC",
  blue: "#DDEBF7",
  green: "#E2F0D9",
  border: "#B8C5BE",
  text: "#202020",
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
  range.format.rowHeight = 32;
}

function bodyStyle(range) {
  range.format = {
    font: { color: COLORS.text, size: 10 },
    verticalAlignment: "top",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "thin", color: "#E3E9E5" },
      bottom: { style: "thin", color: COLORS.border },
    },
  };
}

function statusRules(range) {
  range.conditionalFormats.add("containsText", {
    text: "EXISTING",
    format: { fill: COLORS.green, font: { color: "#375623" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "APPLIED",
    format: { fill: COLORS.blue, font: { color: "#1F4E79" } },
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
    text: "FAILED",
    format: { fill: COLORS.red, font: { color: "#9C0006" } },
  });
}

const detailEnd = Math.max(4, payload.relayRows.length + 3);
const exceptionEnd = Math.max(4, payload.exceptionRows.length + 3);

// Summary
summary.showGridLines = false;
titleBand(
  summary,
  "H",
  "Electric Relay Association Report",
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

summary.getRange("A10:H10").values = [[
  "Substations",
  "Association Rows",
  "Existing",
  "Applied",
  "Proposed",
  "Review",
  "Failed",
  "Exceptions",
]];
headerStyle(summary.getRange("A10:H10"));
summary.getRange("A11:H11").formulas = [[
  "=COUNTA(A15:A500)",
  `=COUNTA('Relay Associations'!$A$4:$A$${detailEnd})`,
  `=COUNTIF('Relay Associations'!$O$4:$O$${detailEnd},"EXISTING")`,
  `=COUNTIF('Relay Associations'!$O$4:$O$${detailEnd},"APPLIED")`,
  `=COUNTIF('Relay Associations'!$O$4:$O$${detailEnd},"PROPOSE")`,
  `=COUNTIF('Relay Associations'!$O$4:$O$${detailEnd},"REVIEW")`,
  `=COUNTIF('Relay Associations'!$O$4:$O$${detailEnd},"FAILED")`,
  `=COUNTA('Exceptions'!$A$4:$A$${exceptionEnd})`,
]];
summary.getRange("A11:H11").format = {
  fill: "#FFFFFF",
  font: { bold: true, color: COLORS.dark, size: 12 },
  horizontalAlignment: "center",
  borders: { preset: "all", style: "thin", color: COLORS.border },
  numberFormat: "#,##0",
};
summary.getRange("A11:H11").format.rowHeight = 26;

summary.getRange("A14:G14").values = [[
  "Substation",
  "Association Rows",
  "Existing",
  "Applied",
  "Proposed",
  "Review / Failed",
  "Exceptions",
]];
headerStyle(summary.getRange("A14:G14"));
if (payload.substations.length) {
  const start = 15;
  const end = start + payload.substations.length - 1;
  summary.getRange(`A${start}:A${end}`).values = payload.substations.map((name) => [name]);
  for (let row = start; row <= end; row += 1) {
    summary.getRange(`B${row}:G${row}`).formulas = [[
      `=COUNTIF('Relay Associations'!$B$4:$B$${detailEnd},$A${row})`,
      `=COUNTIFS('Relay Associations'!$B$4:$B$${detailEnd},$A${row},'Relay Associations'!$O$4:$O$${detailEnd},"EXISTING")`,
      `=COUNTIFS('Relay Associations'!$B$4:$B$${detailEnd},$A${row},'Relay Associations'!$O$4:$O$${detailEnd},"APPLIED")`,
      `=COUNTIFS('Relay Associations'!$B$4:$B$${detailEnd},$A${row},'Relay Associations'!$O$4:$O$${detailEnd},"PROPOSE")`,
      `=COUNTIFS('Relay Associations'!$B$4:$B$${detailEnd},$A${row},'Relay Associations'!$O$4:$O$${detailEnd},"REVIEW")+COUNTIFS('Relay Associations'!$B$4:$B$${detailEnd},$A${row},'Relay Associations'!$O$4:$O$${detailEnd},"FAILED")`,
      `=COUNTIF('Exceptions'!$B$4:$B$${exceptionEnd},$A${row})`,
    ]];
  }
  bodyStyle(summary.getRange(`A${start}:G${end}`));
  summary.getRange(`B${start}:G${end}`).format.numberFormat = "#,##0";
  const table = summary.tables.add(`A14:G${end}`, true, "RelaySubstationSummaryTable");
  table.style = "TableStyleMedium4";
}
summary.freezePanes.freezeRows(2);
summary.getRange("A1:H40").format.font.name = "Aptos";
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 42;
summary.getRange("C:H").format.columnWidth = 16;

// Relay association details
details.showGridLines = false;
titleBand(
  details,
  "P",
  "Relay Association Details",
  "Only spatially scoped and live-rule-valid terminal connections are proposed.",
);
const detailHeaders = [
  "No.",
  "Substation",
  "Relay Record ID",
  "Relay Type",
  "Relay Description",
  "Relay Bay ID",
  "Matched Scope",
  "Bay",
  "Equipment Record ID",
  "Equipment Asset ID",
  "Equipment Group",
  "Equipment Type",
  "Equipment Terminal",
  "Relay Terminal",
  "Status",
  "Assessment",
];
details.getRange("A3:P3").values = [detailHeaders];
headerStyle(details.getRange("A3:P3"));
if (payload.relayRows.length) {
  details.getRange(`A4:P${payload.relayRows.length + 3}`).values =
    payload.relayRows.map((row) => detailHeaders.map((header) => row[header] ?? ""));
  bodyStyle(details.getRange(`A4:P${payload.relayRows.length + 3}`));
  details.getRange(`A4:A${payload.relayRows.length + 3}`).format.numberFormat = "#,##0";
  details.getRange(`C4:C${payload.relayRows.length + 3}`).format.numberFormat = "0";
  details.getRange(`I4:I${payload.relayRows.length + 3}`).format.numberFormat = "0";
  statusRules(details.getRange(`O4:O${payload.relayRows.length + 3}`));
  const table = details.tables.add(
    `A3:P${payload.relayRows.length + 3}`,
    true,
    "RelayAssociationDetailsTable",
  );
  table.style = "TableStyleMedium4";
}
details.freezePanes.freezeRows(3);
details.getRange(`A1:P${Math.max(6, detailEnd + 1)}`).format.font.name = "Aptos";
const detailWidths = [7, 19, 16, 27, 30, 13, 18, 27, 19, 20, 25, 30, 21, 18, 13, 48];
detailWidths.forEach((width, index) => {
  details.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width;
});

// Exceptions
exceptions.showGridLines = false;
titleBand(
  exceptions,
  "G",
  "Relay Association Exceptions",
  "Excluded from Apply. Correct the boundary or relay data, then run Preview again.",
);
const exceptionHeaders = [
  "No.",
  "Substation",
  "Relay Record ID",
  "Relay Type",
  "Relay Bay ID",
  "Status",
  "Assessment",
];
exceptions.getRange("A3:G3").values = [exceptionHeaders];
headerStyle(exceptions.getRange("A3:G3"));
if (payload.exceptionRows.length) {
  exceptions.getRange(`A4:G${payload.exceptionRows.length + 3}`).values =
    payload.exceptionRows.map((row) => exceptionHeaders.map((header) => row[header] ?? ""));
  bodyStyle(exceptions.getRange(`A4:G${payload.exceptionRows.length + 3}`));
  statusRules(exceptions.getRange(`F4:F${payload.exceptionRows.length + 3}`));
  const table = exceptions.tables.add(
    `A3:G${payload.exceptionRows.length + 3}`,
    true,
    "RelayAssociationExceptionsTable",
  );
  table.style = "TableStyleMedium4";
}
exceptions.freezePanes.freezeRows(3);
exceptions.getRange(`A1:G${Math.max(6, exceptionEnd + 1)}`).format.font.name = "Aptos";
const exceptionWidths = [7, 22, 17, 30, 14, 13, 70];
exceptionWidths.forEach((width, index) => {
  exceptions.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width;
});

const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);

if (previewDir) {
  await fs.mkdir(previewDir, { recursive: true });
  for (const sheetName of ["Summary", "Relay Associations", "Exceptions"]) {
    const rendered = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1.2,
      format: "png",
    });
    await fs.writeFile(
      `${previewDir}/${sheetName.toLowerCase().replaceAll(" ", "_")}.png`,
      new Uint8Array(await rendered.arrayBuffer()),
    );
  }
  const inspection = await workbook.inspect({
    kind: "table",
    range: "Summary!A1:H30",
    include: "values,formulas",
    tableMaxRows: 30,
    tableMaxCols: 8,
  });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  console.log(JSON.stringify({ inspection: inspection.ndjson, errors: errors.ndjson }));
}
