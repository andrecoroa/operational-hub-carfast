import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_DECISIONS_URL || "http://127.0.0.1:18766";
const output = path.resolve("docs/evidence/task-decisions-forward-fix/browser");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const evidence = {};

for (const viewport of [
  { name: "desktop", width: 1440, height: 731 },
  { name: "mobile", width: 390, height: 844 },
]) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${base}/login`);
  await page.locator('input[name="email"]').fill("executor.preview@carfast.local");
  await page.locator('input[name="password"]').fill("PreviewOnly123!");
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator('form[action="/login"] button[type="submit"]').click(),
  ]);
  if (page.url().includes("change-notice")) {
    await page.locator('input[type="checkbox"]').check();
    await Promise.all([
      page.waitForLoadState("domcontentloaded"),
      page.locator('form[action="/change-notice"] button[type="submit"]').click(),
    ]);
  }

  const claimUrl = `${base}/v2-clean/tasks?workspace=all&task_scope_view=claim&assignment=unassigned`;
  await page.goto(claimUrl);
  const decisionsLink = page.getByRole("link", { name: "Decisões para mim" });
  await decisionsLink.focus();
  await Promise.all([page.waitForLoadState("domcontentloaded"), decisionsLink.click()]);
  if (new URL(page.url()).search !== "?decision=mine") {
    throw new Error(`${viewport.name}: URL de decisões não canónica: ${page.url()}`);
  }
  if (!(await page.locator("body").innerText()).includes("Validar documentação da reserva sintética")) {
    throw new Error(`${viewport.name}: decisão atribuída ficou oculta`);
  }
  await page.reload();
  const row = page.locator("[data-task-row]").first();
  await row.focus();
  await page.keyboard.press("Enter");
  if (!page.url().includes("#task-")) throw new Error(`${viewport.name}: hash não foi criado`);
  const selectedId = await row.getAttribute("data-task-id");
  if ((await page.evaluate(() => sessionStorage.getItem("carfast.taskSelection"))) !== selectedId) {
    throw new Error(`${viewport.name}: seleção não foi guardada`);
  }
  await page.reload();
  if ((await page.locator('[data-task-row][aria-selected="true"]').count()) !== 1) {
    throw new Error(`${viewport.name}: reload não restaurou seleção`);
  }
  await page.keyboard.press("Escape");
  if (page.url().includes("#task-")) throw new Error(`${viewport.name}: Escape não fechou seleção`);
  if ((await row.evaluate((element) => element === document.activeElement)) !== true) {
    throw new Error(`${viewport.name}: foco não regressou à tarefa`);
  }

  const tasksLink = page
    .getByRole("navigation", { name: "Área do Centro de Tarefas" })
    .getByRole("link", { name: "Tarefas", exact: true });
  await Promise.all([page.waitForLoadState("domcontentloaded"), tasksLink.click()]);
  if (new URL(page.url()).pathname !== "/v2-clean/tasks" || new URL(page.url()).search) {
    throw new Error(`${viewport.name}: saída de decisões não foi canónica`);
  }
  await page.goBack();
  if (new URL(page.url()).search !== "?decision=mine") throw new Error(`${viewport.name}: Back perdeu decisões`);
  await page.goForward();
  for (const label of ["Por categoria", "Por caso", "Lista"]) {
    const button = page.getByRole("button", { name: label });
    await button.click();
    await page.waitForLoadState("domcontentloaded");
  }
  const geometry = await page.evaluate(() => ({ width: innerWidth, bodyWidth: document.body.scrollWidth }));
  if (geometry.bodyWidth > geometry.width) throw new Error(`${viewport.name}: overflow horizontal`);
  await page.screenshot({ path: path.join(output, `${viewport.name}.png`), fullPage: true });
  evidence[viewport.name] = { canonical: true, selectedId, geometry, errors };
  if (errors.length) throw new Error(`${viewport.name}: ${errors.join("; ")}`);
  await page.close();
}

fs.writeFileSync(path.join(output, "result.json"), `${JSON.stringify(evidence, null, 2)}\n`);
await browser.close();
