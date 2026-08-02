import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "C:/Users/andre/OneDrive/Документы/New project/_v2-report-fix";
const payload = JSON.parse(await fs.readFile(`${root}/tmp/bpi_financial_plans.json`, "utf8"));
const rows = payload.records;
const outputDir = `${root}/outputs/bpi-update-20260802`;
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
  Number(r.installment_with_vat), "Cash-flow BPI por contrato",
  `Capital em dívida sem IVA à data de ${r.reference_date}`, r.source,
  "Plano BPI individual associado por contrato e matrícula.",
]);
const associationRows = rows.map((r) => [
  r.entity, r.contract, r.plate, "", "", "", "", "", "Ativa", "Alta",
  "Contrato BPI associado à matrícula no mapa financeiro", r.source,
  "Associação segura por mapa existente.", r.start_date, r.end_date, r.term_months,
  Number(r.initial_amount), Number(r.outstanding_amount), Number(r.installment_amount),
  Number(r.installment_with_vat), Number(r.residual_with_vat),
  `Capital em dívida sem IVA à data de ${r.reference_date}`, r.source,
]);
const monthlyRows = rows.flatMap((r) => r.installments.map((item) => [
  r.entity, r.contract, r.plate, item.period_number, item.period_start, item.period_end,
  Number(item.amortization_amount), Number(item.interest_amount), Number(item.installment_amount),
  Number(item.outstanding_amount), Number(item.outstanding_amount_with_vat),
  `${r.source} · ${item.period_label}`,
]));

const workbook = Workbook.create();
const main = workbook.worksheets.add("Todos os contratos");
const associations = workbook.worksheets.add("Viaturas associadas");
const monthly = workbook.worksheets.add("Plano mensal");

function buildSheet(sheet, headers, data, tableName) {
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, data.length + 1, headers.length).values = [headers, ...data];
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
    fill: "#0B2A56", font: { bold: true, color: "#FFFFFF" }, wrapText: true,
    verticalAlignment: "center", rowHeight: 36,
  };
  sheet.tables.add(
    sheet.getRangeByIndexes(0, 0, data.length + 1, headers.length),
    true,
    tableName,
  ).style = "TableStyleMedium2";
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);
  sheet.getUsedRange().format.autofitColumns();
  sheet.getUsedRange().format.autofitRows();
  for (let column = 0; column < headers.length; column += 1) {
    const range = sheet.getRangeByIndexes(0, column, data.length + 1, 1);
    range.format.columnWidth = Math.min(Math.max(range.format.columnWidth || 12, 12), 28);
  }
}

buildSheet(main, mainHeaders, mainRows, "BpiContracts");
buildSheet(associations, associationHeaders, associationRows, "BpiAssociations");
buildSheet(monthly, monthlyHeaders, monthlyRows, "BpiMonthly");

for (const sheet of [main, associations]) {
  const headers = sheet.getRangeByIndexes(0, 0, 1, sheet.getUsedRange().columnCount).values[0];
  for (const label of ["Data início", "Data fim"]) {
    const index = headers.indexOf(label);
    sheet.getRangeByIndexes(1, index, rows.length, 1).format.numberFormat = "yyyy-mm-dd";
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

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/Planos_BPI_completos_20260802.xlsx`);
await fs.writeFile(
  `${outputDir}/Contratos_BPI_por_associar.txt`,
  [
    ...payload.unmatched.map((contract) => `${contract} | sem matrícula`),
    ...payload.incomplete.map((item) => `${item.contract} | ${item.plate} | plano sem mensalidades`),
  ].join("\n") + "\n",
  "utf8",
);
console.log(`${rows.length} planos e ${monthlyRows.length} mensalidades exportados.`);
