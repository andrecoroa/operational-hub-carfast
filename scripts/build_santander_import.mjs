import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "C:/Users/andre/OneDrive/Документы/New project/_v2-report-fix";
const payload = JSON.parse(await fs.readFile(`${root}/tmp/santander_financial_plans.json`, "utf8"));
const rows = payload.records;
const outputDir = `${root}/outputs/santander-update-20260802`;
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
  Number(r.installment_amount), "Quadro de amortizações Santander",
  `Capital em dívida sem IVA em ${r.reference_date}`, `${r.source}; ${r.catalog_source}`,
  r.inherited_from_batch
    ? `Plano repetido do contrato-base ${r.plan_contract}; unidade ${r.contract} do mesmo lote.`
    : "Valores mensais extraídos do PDF; associação por contrato e matrícula do mapa Santander.",
]);
const associationRows = rows.map((r) => [
  r.entity, r.contract, r.plate, "", "", "", "", "", "Ativa", "Alta",
  "Contrato Santander associado à matrícula no mapa de contratos ativos", r.source,
  r.inherited_from_batch
    ? `Associação segura; plano comum do lote ${r.plan_contract.slice(0, -2)}.`
    : "Associação segura por contrato.", r.start_date, r.end_date, r.term_months,
  Number(r.initial_amount), Number(r.outstanding_amount), Number(r.installment_amount),
  Number(r.installment_amount), Number(r.residual_with_vat),
  `Capital em dívida sem IVA em ${r.reference_date}`, `${r.source}; ${r.catalog_source}`,
]);
const monthlyRows = rows.flatMap((r) => r.installments.map((item) => [
  r.entity, r.contract, r.plate, item.period_number, item.period_start, item.period_end,
  Number(item.amortization_amount), Number(item.interest_amount), Number(item.installment_amount),
  Number(item.outstanding_amount), Number(item.outstanding_amount_with_vat),
  `${r.source} · plano ${r.plan_contract} · data ${item.date_source}`,
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

buildSheet(main, mainHeaders, mainRows, "SantanderContracts");
buildSheet(associations, associationHeaders, associationRows, "SantanderAssociations");
buildSheet(monthly, monthlyHeaders, monthlyRows, "SantanderMonthly");
for (const label of ["Amortização (€)", "Juros (€)", "Prestação (€)", "Capital em dívida (€)", "Capital em dívida c/IVA (€)"]) {
  const index = monthlyHeaders.indexOf(label);
  monthly.getRangeByIndexes(1, index, monthlyRows.length, 1).format.numberFormat = '#,##0.00 "€"';
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/Planos_Santander_completos_20260802.xlsx`);
await fs.writeFile(
  `${outputDir}/Contratos_Santander_sem_plano.txt`,
  [
    "CONTRATOS DO MAPA SEM PDF",
    ...payload.catalog_without_pdf,
    "",
    "PLANOS PDF SEM MATRÍCULA NO MAPA",
    ...payload.unmatched.map((item) => `${item.contract} | ${item.source}`),
    "",
    "PLANOS INCOMPLETOS",
    ...payload.incomplete.map((item) => `${item.contract} | ${item.plate} | ${item.reason}`),
  ].join("\n") + "\n",
  "utf8",
);
console.log(`${rows.length} planos e ${monthlyRows.length} mensalidades exportados.`);
