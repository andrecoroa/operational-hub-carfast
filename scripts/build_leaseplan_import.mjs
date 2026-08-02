import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "C:/Users/andre/OneDrive/Документы/New project/_v2-report-fix";
const rows = JSON.parse(await fs.readFile(`${root}/tmp/leaseplan_updates.json`, "utf8"));
const outputDir = `${root}/outputs/leaseplan-update-20260802`;
await fs.mkdir(outputDir, { recursive: true });

const mainHeaders = [
  "Financeira", "Contrato", "Estado associação", "N.º viaturas", "Matrículas",
  "VIN/chassis", "Confiança", "Data início", "Data fim", "Prazo (meses)",
  "Capital inicial (€)", "Saldo conhecido (€)", "Renda financeira (€)", "Taxa juro",
  "Spread", "Valor residual (€)", "Encargos/renda c/IVA (€)", "Qualidade financeira",
  "Base temporal / definição", "Fontes consolidadas", "Observações",
];
const associationHeaders = [
  "Financeira", "Contrato", "Matrícula", "VIN/chassis", "Unidade", "Marca", "Modelo",
  "Versão", "Estado viatura", "Confiança", "Evidência", "Fontes", "Observações",
  "Data início", "Data fim", "Prazo (meses)", "Capital inicial (€)", "Saldo conhecido (€)",
  "Renda financeira (€)", "Encargos/renda c/IVA (€)", "Valor residual (€)",
  "Base temporal / definição", "Fontes consolidadas",
];
const monthlyHeaders = [
  "Financeira", "Contrato", "Matrícula", "Período", "Data início", "Data fim",
  "Amortização (€)", "Juros (€)", "Prestação (€)", "Capital em dívida (€)",
  "Capital em dívida c/IVA (€)", "Fonte",
];

const mainRows = rows.map((r) => [
  r.entity, r.contract, "Associado", 1, r.plate, "", "Alta", r.start_date, r.end_date,
  r.term_months, Number(r.initial_amount), Number(r.outstanding_amount),
  Number(r.installment_amount), "", "", Number(r.residual_with_vat),
  Number(r.installment_with_vat), "Fonte LeasePlan por matrícula",
  `Capital em dívida sem IVA à data de ${r.reference_date}`,
  r.source,
  `Plano LeasePlan individual; documento de origem ${r.source_document_date}.`,
]);
const associationRows = rows.map((r) => [
  r.entity, r.contract, r.plate, "", "", "", "", "", "Ativa", "Alta",
  "Matrícula indicada no separador individual do plano de amortização", r.source,
  "Atualização segura por correspondência exata de matrícula.", r.start_date, r.end_date,
  r.term_months, Number(r.initial_amount), Number(r.outstanding_amount),
  Number(r.installment_amount), Number(r.installment_with_vat), Number(r.residual_with_vat),
  `Capital em dívida sem IVA à data de ${r.reference_date}`, r.source,
]);
const monthlyRows = rows.flatMap((r) => r.installments.map((item) => [
  r.entity, r.contract, r.plate, item.period_number, item.period_start, item.period_end,
  Number(item.amortization_amount), Number(item.interest_amount), Number(item.installment_amount),
  Number(item.outstanding_amount), Number(item.outstanding_amount_with_vat), r.source,
]));

const workbook = Workbook.create();
const main = workbook.worksheets.add("Todos os contratos");
const associations = workbook.worksheets.add("Viaturas associadas");
const monthly = workbook.worksheets.add("Plano mensal");

function buildSheet(sheet, headers, data, tableName) {
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, data.length + 1, headers.length).values = [headers, ...data];
  const header = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  header.format = {
    fill: "#0B2A56",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  header.format.rowHeight = 36;
  const body = sheet.getRangeByIndexes(1, 0, data.length, headers.length);
  body.format = {
    font: { color: "#10244A" },
    borders: { insideHorizontal: { style: "thin", color: "#D8E0EA" } },
    verticalAlignment: "top",
  };
  sheet.tables.add(sheet.getRangeByIndexes(0, 0, data.length + 1, headers.length), true, tableName).style = "TableStyleMedium2";
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);
  sheet.getUsedRange().format.autofitColumns();
  sheet.getUsedRange().format.autofitRows();
  for (let c = 0; c < headers.length; c += 1) {
    const column = sheet.getRangeByIndexes(0, c, data.length + 1, 1);
    const width = Math.min(Math.max(column.format.columnWidth || 12, 12), 28);
    column.format.columnWidth = width;
  }
}

buildSheet(main, mainHeaders, mainRows, "LeasePlanContracts");
buildSheet(associations, associationHeaders, associationRows, "LeasePlanAssociations");
buildSheet(monthly, monthlyHeaders, monthlyRows, "LeasePlanMonthly");

for (const sheet of [main, associations]) {
  const headers = sheet.getRangeByIndexes(0, 0, 1, sheet.getUsedRange().columnCount).values[0];
  for (const label of ["Data início", "Data fim"]) {
    const index = headers.indexOf(label);
    if (index >= 0) sheet.getRangeByIndexes(1, index, rows.length, 1).format.numberFormat = "yyyy-mm-dd";
  }
  for (const label of ["Capital inicial (€)", "Saldo conhecido (€)", "Renda financeira (€)", "Valor residual (€)", "Encargos/renda c/IVA (€)"]) {
    const index = headers.indexOf(label);
    if (index >= 0) sheet.getRangeByIndexes(1, index, rows.length, 1).format.numberFormat = '#,##0.00 "€"';
  }
}

for (const label of ["Data início", "Data fim"]) {
  const index = monthlyHeaders.indexOf(label);
  monthly.getRangeByIndexes(1, index, monthlyRows.length, 1).format.numberFormat = "yyyy-mm-dd";
}
for (const label of ["Amortização (€)", "Juros (€)", "Prestação (€)", "Capital em dívida (€)", "Capital em dívida c/IVA (€)"]) {
  const index = monthlyHeaders.indexOf(label);
  monthly.getRangeByIndexes(1, index, monthlyRows.length, 1).format.numberFormat = '#,##0.00 "€"';
}

const summary = await workbook.inspect({ kind: "table", range: "Todos os contratos!A1:U8", include: "values,formulas", tableMaxRows: 8, tableMaxCols: 21 });
console.log(summary.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula errors" });
console.log(errors.ndjson);

for (const sheetName of ["Todos os contratos", "Viaturas associadas", "Plano mensal"]) {
  const preview = await workbook.render({ sheetName, range: "A1:W10", scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${sheetName.replaceAll(" ", "_")}.png`, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/Planos_LeasePlan_atualizados_20260802.xlsx`);
console.log(`${rows.length} planos exportados.`);
