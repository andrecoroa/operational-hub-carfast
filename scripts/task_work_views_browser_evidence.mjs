import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_WORK_VIEWS_URL || "http://127.0.0.1:18768";
const output = path.resolve("docs/evidence/task-work-views/browser");
fs.mkdirSync(output, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const results = {};
for (const viewport of [
  { name: "desktop", width: 1440, height: 731 },
  { name: "mobile", width: 390, height: 844 },
]) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${base}/login`);
  await page.locator('input[name="email"]').fill("queue.preview@carfast.local");
  await page.locator('input[name="password"]').fill("PreviewOnly123!");
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator('form[action="/login"] button[type="submit"]').click(),
  ]);
  if (page.url().includes("change-notice")) {
    const checkbox = page.locator('input[type="checkbox"]');
    if (await checkbox.count()) await checkbox.check();
    await Promise.all([
      page.waitForLoadState("domcontentloaded"),
      page.locator('form[action="/change-notice"] button[type="submit"]').click(),
    ]);
  }

  await page.goto(`${base}/v2-clean/tasks?queue=tasks_support&status=open`);
  const defaultRows = await page.locator("[data-task-row]").count();
  const relation = page.locator('[data-task-mine-relation-select]');
  if ((await relation.inputValue()) !== "assigned" || defaultRows < 1) {
    throw new Error(`${viewport.name}: Minhas não iniciou em atribuídas`);
  }
  const labels = await relation.locator("option").allTextContents();
  if (labels.join("|") !== "Atribuídas a mim|Todas as minhas|Criadas por mim|A acompanhar") {
    throw new Error(`${viewport.name}: relações inesperadas ${labels.join("|")}`);
  }
  const geometry = await page.evaluate(() => ({
    bodyWidth: document.body.scrollWidth,
    viewportWidth: innerWidth,
    scrollMax: document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight,
  }));
  if (geometry.bodyWidth > geometry.viewportWidth) throw new Error(`${viewport.name}: overflow horizontal`);

  const claim = await page.request.get(`${base}/v2-clean/tasks?task_scope_view=claim&workspace=all&mine_kind=assigned&assignment=unassigned&status=all`);
  const claimText = await claim.text();
  if (claim.status() !== 200 || !claimText.includes("Preparar entrada de viatura na oficina")) {
    throw new Error(`${viewport.name}: Por assumir não mostrou a tarefa elegível`);
  }
  const forged = await page.request.get(`${base}/v2-clean/tasks?task_scope_view=mine&mine_kind=forged`);
  if (forged.status() !== 400) throw new Error(`${viewport.name}: relação forjada não rejeitada`);
  const incompatible = await page.request.get(`${base}/v2-clean/tasks?task_scope_view=mine&assignment=unassigned`);
  if (incompatible.status() !== 400) throw new Error(`${viewport.name}: combinação incompatível aceite`);
  const workspaceBypass = await page.request.get(`${base}/v2-clean/tasks?workspace=tasks_support`);
  if (workspaceBypass.status() !== 400) throw new Error(`${viewport.name}: bypass por workspace aceite`);
  const claimFallback = await page.request.get(`${base}/v2-clean/tasks?task_scope_view=claim&workspace=mine`);
  if (claimFallback.status() !== 400) throw new Error(`${viewport.name}: fallback claim/mine aceite`);

  const team = await page.request.get(`${base}/v2-clean/tasks?task_scope_view=team&status=all`);
  if (team.status() !== 200) throw new Error(`${viewport.name}: Da equipa devolveu ${team.status()}`);
  const teamText = await team.text();
  if (!teamText.includes("Preparar entrada de viatura na oficina") || teamText.includes("Confirmar fatura e arquivo do dossier")) {
    throw new Error(`${viewport.name}: Da equipa regressou silenciosamente a Minhas`);
  }

  await page.screenshot({ path: path.join(output, `${viewport.name}.png`), fullPage: true });
  results[viewport.name] = { defaultRows, labels, geometry, claim: claim.status(), forged: forged.status(), incompatible: incompatible.status(), workspaceBypass: workspaceBypass.status(), claimFallback: claimFallback.status(), team: team.status(), errors };
  if (errors.length) throw new Error(`${viewport.name}: ${errors.join("; ")}`);
  await page.close();
}
fs.writeFileSync(path.join(output, "result.json"), `${JSON.stringify(results, null, 2)}\n`);
await browser.close();
