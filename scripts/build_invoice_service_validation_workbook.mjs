import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputDir = process.argv[2];
const outputPath = process.argv[3];
const exclusionsPath = process.argv[4];
if (!inputDir || !outputPath || !exclusionsPath) {
  throw new Error("Usage: node script.mjs <input-dir> <output.xlsx> <blocked-ledger.csv>");
}

const dryRun = JSON.parse(await fs.readFile(path.join(inputDir, "invoice_service_remediation_dry_run.json"), "utf8"));
const exclusionsText = await fs.readFile(exclusionsPath, "utf8");
const parseSemicolon = (text) => {
  const lines = text.replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const headers = lines.shift().split(";");
  return lines.map((line) => {
    const values = line.split(";");
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
  });
};
const exclusions = parseSemicolon(exclusionsText);
if (exclusions.length !== 716) throw new Error(`Expected 716 exclusions, found ${exclusions.length}`);

const workbook = Workbook.create();
const font = "Arial";
const navy = "#17365D";
const blue = "#D9EAF7";
const amber = "#FFF2CC";
const paleRed = "#FCE4D6";
const green = "#E2F0D9";
const bodyFont = { name: font, size: 10, color: "#1F1F1F" };
const headerFormat = {
  fill: navy,
  font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};

function styleTitle(sheet, title, subtitle, endColumn = "H") {
  sheet.showGridLines = false;
  sheet.getRange("A2").values = [[title]];
  sheet.getRange("A2").format.font = { name: font, size: 15, bold: true, color: "#1F1F1F" };
  sheet.getRange(`A3:${endColumn}3`).format.borders = { bottom: { style: "thin", color: "#4472C4" } };
  sheet.getRange("A4").values = [[subtitle]];
  sheet.getRange("A4").format.font = { name: font, size: 10, italic: true, color: "#595959" };
}

const summary = workbook.worksheets.add("Resumo");
styleTitle(summary, "Remediação de serviços de faturas", "Dry-run local. Não executa importação nem altera o Green.", "J");
const summaryRows = [
  ["Métrica", "Resultado"],
  ["Documentos elegíveis", dryRun.summary.eligible_documents],
  ["Linhas de serviço", dryRun.summary.service_rows],
  ["Documentos com serviços", dryRun.summary.documents_with_services],
  ["Linhas bloqueadas excluídas", dryRun.blocked_ledger.count],
  ["Chaves duplicadas", dryRun.summary.duplicate_stable_keys.length],
  ["Linhas relevantes sem regra", dryRun.summary.unassigned_relevant_lines],
  ["Total específico dos serviços", Number(dryRun.summary.service_amount_total)],
  ["Total das faturas", Number(dryRun.summary.invoice_total)],
  ["Total das linhas fonte", Number(dryRun.summary.source_line_total)],
];
summary.getRangeByIndexes(6, 0, summaryRows.length, 2).values = summaryRows;
summary.getRange("A7:B7").format = headerFormat;
summary.getRange(`A8:B${6 + summaryRows.length}`).format.font = bodyFont;
summary.getRange(`B14:B${6 + summaryRows.length}`).format.numberFormat = "#,##0.00 [$€-pt-PT]";
summary.getRange("A:A").format.columnWidth = 38;
summary.getRange("B:B").format.columnWidth = 24;
summary.getRange("D7:H7").values = [["Documento", "Presente", "Serviços", "Códigos", "Valor alocado"]];
summary.getRange("D7:H7").format = headerFormat;
const acceptanceRows = Object.entries(dryRun.acceptance_documents).map(([documentId, item]) => [
  Number(documentId), item.present ? "Sim" : "Não", item.service_count, item.codes.join(", "), Number(item.allocated_amount),
]);
summary.getRangeByIndexes(7, 3, acceptanceRows.length, 5).values = acceptanceRows;
summary.getRange(`D8:H${7 + acceptanceRows.length}`).format.font = bodyFont;
summary.getRange(`H8:H${7 + acceptanceRows.length}`).format.numberFormat = "#,##0.00 [$€-pt-PT]";
summary.getRange("D:D").format.columnWidth = 14;
summary.getRange("E:F").format.columnWidth = 12;
summary.getRange("G:G").format.columnWidth = 64;
summary.getRange("H:H").format.columnWidth = 18;
summary.tabColor = navy;

const validation = workbook.worksheets.add("Validação");
styleTitle(validation, "Serviços propostos para validação", "Preencher apenas Aprovar, Corrigir ou Excluir. A evidência e os valores permanecem rastreáveis às linhas fonte.", "X");
const validationHeaders = [
  "Chave estável", "Matrícula", "VIN", "Documento ID", "Fatura", "Data", "KM", "Categoria",
  "Código", "Subcategoria", "Eixo", "Linhas fonte", "Descrições fonte", "Peças", "Mão de obra",
  "Valor serviço", "Confiança", "Motivo", "Projeção documental", "Abrir fatura", "Aprovar", "Corrigir", "Excluir",
];
const validationRows = dryRun.services.map((row, index) => [
  row.stable_key, row.plate, row.vin, row.document_id, row.document_number,
  row.document_date ? new Date(`${row.document_date}T00:00:00Z`) : "",
  row.odometer_km ? Number(row.odometer_km) : "", row.category, row.service_code, row.subcategory,
  row.axle, row.source_line_ids, row.source_descriptions, row.parts, row.labor,
  Number(row.service_amount), Number(row.confidence), row.confidence_reason, row.document_projection,
  `=HYPERLINK("${row.invoice_link}","Abrir fatura")`, "", "", "",
]);
validation.getRangeByIndexes(6, 0, 1, validationHeaders.length).values = [validationHeaders];
validation.getRangeByIndexes(7, 0, validationRows.length, validationHeaders.length).values = validationRows.map((row) => row.map((value, column) => column === 19 ? "" : value));
validation.getRangeByIndexes(7, 19, validationRows.length, 1).formulas = validationRows.map((row) => [row[19]]);
validation.getRangeByIndexes(6, 0, 1, validationHeaders.length).format = headerFormat;
validation.getRangeByIndexes(7, 0, validationRows.length, validationHeaders.length).format.font = bodyFont;
validation.getRangeByIndexes(7, 5, validationRows.length, 1).format.numberFormat = "dd/mm/yyyy";
validation.getRangeByIndexes(7, 6, validationRows.length, 1).format.numberFormat = "#,##0";
validation.getRangeByIndexes(7, 15, validationRows.length, 1).format.numberFormat = "#,##0.00 [$€-pt-PT]";
validation.getRangeByIndexes(7, 16, validationRows.length, 1).format.numberFormat = "0.00";
validation.getRange(`U8:W${7 + validationRows.length}`).format.fill = amber;
validation.getRange(`U8:W${7 + validationRows.length}`).dataValidation = { rule: { type: "list", values: ["", "Sim"] } };
validation.getRange(`U8:U${7 + validationRows.length}`).conditionalFormats.add("containsText", { text: "Sim", format: { fill: green, font: { bold: true, color: "#375623" } } });
validation.getRange(`W8:W${7 + validationRows.length}`).conditionalFormats.add("containsText", { text: "Sim", format: { fill: paleRed, font: { bold: true, color: "#9C0006" } } });
validation.getRange("A:A").format.columnWidth = 42;
validation.getRange("B:C").format.columnWidth = 20;
validation.getRange("D:D").format.columnWidth = 12;
validation.getRange("E:E").format.columnWidth = 26;
validation.getRange("F:G").format.columnWidth = 13;
validation.getRange("H:K").format.columnWidth = 18;
validation.getRange("L:L").format.columnWidth = 24;
validation.getRange("M:O").format.columnWidth = 45;
validation.getRange("P:Q").format.columnWidth = 15;
validation.getRange("R:R").format.columnWidth = 48;
validation.getRange("S:S").format.columnWidth = 24;
validation.getRange("T:W").format.columnWidth = 15;
validation.getRange(`M8:R${7 + validationRows.length}`).format.wrapText = true;
validation.freezePanes.freezeRows(7);
validation.freezePanes.freezeColumns(5);
validation.tables.add(`A7:W${7 + validationRows.length}`, true, "ServiceValidationTable").style = "TableStyleMedium2";
validation.tabColor = "#4472C4";

const reconciliation = workbook.worksheets.add("Reconciliação");
styleTitle(reconciliation, "Reconciliação por fatura", "O valor de serviço soma apenas linhas atribuídas. Diferenças para o total da fatura ficam visíveis e não são distribuídas artificialmente.", "I");
const reconHeaders = ["Documento ID", "Fatura", "Total fatura", "Total linhas fonte", "Total serviços", "Excluído ou não atribuído", "Fatura menos linhas", "Controlo de alocação", "Projeção"];
const reconRows = dryRun.reconciliations.map((row) => [row.document_id, row.document_number, Number(row.invoice_total), Number(row.source_line_total), Number(row.service_total), Number(row.excluded_or_unassigned_total), Number(row.invoice_minus_source_lines), Number(row.allocation_check), row.document_projection]);
reconciliation.getRangeByIndexes(6, 0, 1, reconHeaders.length).values = [reconHeaders];
reconciliation.getRangeByIndexes(7, 0, reconRows.length, reconHeaders.length).values = reconRows;
reconciliation.getRangeByIndexes(6, 0, 1, reconHeaders.length).format = headerFormat;
reconciliation.getRangeByIndexes(7, 0, reconRows.length, reconHeaders.length).format.font = bodyFont;
reconciliation.getRangeByIndexes(7, 2, reconRows.length, 6).format.numberFormat = "#,##0.00 [$€-pt-PT]";
reconciliation.getRange("A:A").format.columnWidth = 14;
reconciliation.getRange("B:B").format.columnWidth = 28;
reconciliation.getRange("C:H").format.columnWidth = 21;
reconciliation.getRange("I:I").format.columnWidth = 26;
reconciliation.freezePanes.freezeRows(7);
reconciliation.tables.add(`A7:I${7 + reconRows.length}`, true, "InvoiceReconciliationTable").style = "TableStyleMedium2";

const missing = workbook.worksheets.add("Faltas");
styleTitle(missing, "Linhas relevantes sem regra determinística", "Estas linhas exigem revisão humana; nenhuma foi forçada para uma categoria.", "F");
const missingHeaders = ["Documento ID", "Fatura", "Linha fonte", "Descrição", "Valor", "Motivo"];
const missingRows = dryRun.missing_lines.map((row) => [row.document_id, row.document_number, row.source_line_id, row.description, Number(row.amount), row.reason]);
missing.getRangeByIndexes(6, 0, 1, missingHeaders.length).values = [missingHeaders];
missing.getRangeByIndexes(7, 0, missingRows.length, missingHeaders.length).values = missingRows;
missing.getRangeByIndexes(6, 0, 1, missingHeaders.length).format = headerFormat;
missing.getRangeByIndexes(7, 0, missingRows.length, missingHeaders.length).format.font = bodyFont;
missing.getRangeByIndexes(7, 4, missingRows.length, 1).format.numberFormat = "#,##0.00 [$€-pt-PT]";
missing.getRange("A:A").format.columnWidth = 14;
missing.getRange("B:B").format.columnWidth = 28;
missing.getRange("C:C").format.columnWidth = 18;
missing.getRange("D:D").format.columnWidth = 55;
missing.getRange("E:E").format.columnWidth = 16;
missing.getRange("F:F").format.columnWidth = 38;
missing.freezePanes.freezeRows(7);
missing.tables.add(`A7:F${7 + missingRows.length}`, true, "MissingRulesTable").style = "TableStyleMedium4";

const frequency = workbook.worksheets.add("Frequência");
styleTitle(frequency, "Frequência das propostas", "Contagem por código e eixo, sem incluir os 716 serviços bloqueados.", "C");
const frequencyHeaders = ["Código", "Eixo", "Contagem"];
const frequencyRows = dryRun.frequencies.map((row) => [row.service_code, row.axle, row.count]);
frequency.getRangeByIndexes(6, 0, 1, 3).values = [frequencyHeaders];
frequency.getRangeByIndexes(7, 0, frequencyRows.length, 3).values = frequencyRows;
frequency.getRange("A7:C7").format = headerFormat;
frequency.getRangeByIndexes(7, 0, frequencyRows.length, 3).format.font = bodyFont;
frequency.getRange("A:A").format.columnWidth = 28;
frequency.getRange("B:B").format.columnWidth = 18;
frequency.getRange("C:C").format.columnWidth = 14;
frequency.tables.add(`A7:C${7 + frequencyRows.length}`, true, "ServiceFrequencyTable").style = "TableStyleMedium2";

const blocked = workbook.worksheets.add("Exclusões 716");
styleTitle(blocked, "Exclusões formais preservadas", "Registos bloqueados mantidos sem correção, associação ou proposta de importação.", "N");
const blockedHeaders = Object.keys(exclusions[0]);
blocked.getRangeByIndexes(6, 0, 1, blockedHeaders.length).values = [blockedHeaders];
blocked.getRangeByIndexes(7, 0, exclusions.length, blockedHeaders.length).values = exclusions.map((row) => blockedHeaders.map((header) => row[header] ?? ""));
blocked.getRangeByIndexes(6, 0, 1, blockedHeaders.length).format = headerFormat;
blocked.getRangeByIndexes(7, 0, exclusions.length, blockedHeaders.length).format.font = { name: font, size: 9, color: "#595959" };
blocked.getRangeByIndexes(7, 0, exclusions.length, blockedHeaders.length).format.fill = "#F2F2F2";
for (let column = 0; column < blockedHeaders.length; column++) blocked.getRangeByIndexes(0, column, 1, 1).format.columnWidth = 20;
blocked.freezePanes.freezeRows(7);
blocked.freezePanes.freezeColumns(3);
blocked.tables.add(`A7:${String.fromCharCode(64 + blockedHeaders.length)}${7 + exclusions.length}`, true, "FormalExclusionsTable").style = "TableStyleMedium15";

workbook.recalculate();
const summaryInspect = await workbook.inspect({ kind: "table", range: "Resumo!A2:H18", include: "values,formulas", tableMaxRows: 18, tableMaxCols: 8 });
console.log(summaryInspect.ndjson);
const validationInspect = await workbook.inspect({ kind: "table", range: "Validação!A7:W12", include: "values,formulas", tableMaxRows: 6, tableMaxCols: 23 });
console.log(validationInspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
console.log(errors.ndjson);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const previewRanges = {
  "Resumo": "A1:J18",
  "Validação": "A1:W18",
  "Reconciliação": "A1:I22",
  "Faltas": "A1:F22",
  "Frequência": "A1:C30",
  "Exclusões 716": "A1:N18",
};
for (const [sheetName, range] of Object.entries(previewRanges)) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(path.dirname(outputPath), `preview_${sheetName.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ output: outputPath, sheets: workbook.worksheets.items.map((sheet) => sheet.name), rows: validationRows.length, exclusions: exclusions.length }));
