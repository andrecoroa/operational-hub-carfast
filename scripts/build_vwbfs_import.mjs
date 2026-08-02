import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "C:/Users/andre/OneDrive/Документы/New project/_v2-report-fix";
const payload = JSON.parse(await fs.readFile(`${root}/tmp/vwbfs_financial_plans.json`, "utf8"));
const rows = payload.records;
const outputDir = `${root}/outputs/vwbfs-update-20260802`;
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
  r.entity, r.contract, "Associado", 1, r.plate, r.vin, "Alta", r.start_date, r.end_date,
  r.term_months, Number(r.initial_amount), Number(r.outstanding_amount),
  Number(r.installment_amount), "", r.spread, Number(r.residual_with_vat),
  Number(r.installment_with_vat), "Plano mensal VWBFS por contrato",
  `Capital em dívida sem IVA em ${r.reference_date}`, `${r.source}; ${r.source}`,
  "Plano integral associado por contrato, matrícula e VIN.",
]);
const associationRows = rows.map((r) => [
  r.entity, r.contract, r.plate, r.vin, r.unit, r.brand, r.model, r.version, "Ativa", "Alta",
  "Contrato VWBFS cruzado com a frota por número de contrato", r.source,
  "Associação segura pelo mapa financeiro da frota.", r.start_date, r.end_date, r.term_months,
  Number(r.initial_amount), Number(r.outstanding_amount), Number(r.installment_amount),
  Number(r.installment_with_vat), Number(r.residual_with_vat),
  `Capital em dívida sem IVA em ${r.reference_date}`, r.source,
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
  sheet.tables.add(sheet.getRangeByIndexes(0, 0, data.length + 1, headers.length), true, tableName).style = "TableStyleMedium2";
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(3);
  sheet.getUsedRange().format.autofitColumns();
  sheet.getUsedRange().format.autofitRows();
  for (let column = 0; column < headers.length; column += 1) {
    const range = sheet.getRangeByIndexes(0, column, data.length + 1, 1);
    range.format.columnWidth = Math.min(Math.max(range.format.columnWidth || 12, 12), 28);
  }
}

buildSheet(main, mainHeaders, mainRows, "VwbfsContracts");
buildSheet(associations, associationHeaders, associationRows, "VwbfsAssociations");
buildSheet(monthly, monthlyHeaders, monthlyRows, "VwbfsMonthly");
for (const label of ["Amortização (€)", "Juros (€)", "Prestação (€)", "Capital em dívida (€)", "Capital em dívida c/IVA (€)"]) {
  const index = monthlyHeaders.indexOf(label);
  monthly.getRangeByIndexes(1, index, monthlyRows.length, 1).format.numberFormat = '#,##0.00 "€"';
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/Planos_Volkswagen_completos_20260802.xlsx`);
await fs.writeFile(
  `${outputDir}/Contratos_Volkswagen_pendentes.txt`,
  [
    ...payload.unmatched.map((contract) => `${contract} | sem matrícula`),
    ...payload.incomplete.map((item) => `${item.contract} | ${item.plate} | plano incompleto`),
  ].join("\n") + "\n",
  "utf8",
);
console.log(`${rows.length} planos e ${monthlyRows.length} períodos exportados.`);
