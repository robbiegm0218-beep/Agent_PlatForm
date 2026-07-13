import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [outputPath, title, content] = process.argv.slice(2);
if (!outputPath || !title) throw new Error("缺少 Excel 产物参数");

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("回答");
sheet.showGridLines = false;
sheet.getRange("A1:B1").merge();
sheet.getRange("A1").values = [[title]];
sheet.getRange("A1:B1").format = {
  fill: "#0F766E",
  font: { bold: true, color: "#FFFFFF", size: 14 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange("A2:B2").values = [["字段", "内容"]];
sheet.getRange("A2:B2").format = {
  fill: "#CCFBF1",
  font: { bold: true, color: "#134E4A" },
  horizontalAlignment: "center",
};
sheet.getRange("A3:B3").values = [["Agent 回答", content || "（无内容）"]];
sheet.getRange("A2:B3").format.borders = { preset: "all", style: "thin", color: "#99F6E4" };
sheet.getRange("A1:B3").format.wrapText = true;
sheet.getRange("A1:B1").format.rowHeight = 28;
sheet.getRange("A3:B3").format.rowHeight = 180;
sheet.getRange("A1").format.columnWidth = 22;
sheet.getRange("B1").format.columnWidth = 72;
sheet.freezePanes.freezeRows(2);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const file = await SpreadsheetFile.exportXlsx(workbook);
await file.save(outputPath);
