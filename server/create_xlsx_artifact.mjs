import fs from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";

const [outputPath, title, content] = process.argv.slice(2);
if (!outputPath || !title) throw new Error("缺少 Excel 产物参数");

const workbook = new ExcelJS.Workbook();
const sheet = workbook.addWorksheet("回答");
sheet.properties.showGridLines = false;

// Title row (A1:B1 merged)
sheet.mergeCells("A1:B1");
const titleCell = sheet.getCell("A1");
titleCell.value = title;
titleCell.font = { bold: true, color: { argb: "FFFFFFFF" }, size: 14 };
titleCell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF0F766E" } };
titleCell.alignment = { horizontal: "center", vertical: "middle", wrapText: true };

// Header row
const fieldCell = sheet.getCell("A2");
fieldCell.value = "字段";
fieldCell.font = { bold: true, color: { argb: "FF134E4A" } };
fieldCell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFCCFBF1" } };
fieldCell.alignment = { horizontal: "center", vertical: "middle" };

const contentHeaderCell = sheet.getCell("B2");
contentHeaderCell.value = "内容";
contentHeaderCell.font = { bold: true, color: { argb: "FF134E4A" } };
contentHeaderCell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFCCFBF1" } };
contentHeaderCell.alignment = { horizontal: "center", vertical: "middle" };

// Answer row
const answerCell = sheet.getCell("A3");
answerCell.value = "Agent 回答";
answerCell.alignment = { wrapText: true, vertical: "top" };

const contentCell = sheet.getCell("B3");
contentCell.value = content || "（无内容）";
contentCell.alignment = { wrapText: true, vertical: "top" };

// Borders for A2:B3
const thinBorder = { style: "thin", color: { argb: "FF99F6E4" } };
for (const row of [2, 3]) {
  for (const col of ["A", "B"]) {
    const cell = sheet.getCell(`${col}${row}`);
    cell.border = { top: thinBorder, left: thinBorder, bottom: thinBorder, right: thinBorder };
  }
}

// Row heights and column widths
sheet.getRow(1).height = 28;
sheet.getRow(3).height = 180;
sheet.getColumn("A").width = 22;
sheet.getColumn("B").width = 72;

// Freeze panes
sheet.views = [{ state: "frozen", ySplit: 2 }];

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await workbook.xlsx.writeFile(outputPath);
