import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = process.env.TASK_CENTER_PREVIEW_URL || "http://127.0.0.1:18766";
const output = path.resolve(process.env.TASK_CENTER_EVIDENCE_DIR || "docs/evidence/task-center-actions-parity");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 731 } });

await page.goto(`${base}/login`);
await page.locator('input[name="email"]').fill("executor.preview@carfast.local");
await page.locator('input[name="password"]').fill("PreviewOnly123!");
await page.locator('form[action="/login"] button[type="submit"]').click();
await page.waitForTimeout(750);
if (page.url().endsWith("/login")) throw new Error(`Login failed: ${(await page.locator("body").innerText()).slice(0, 500)}`);
if (page.url().includes("change-notice")) {
  await page.locator('form[action="/change-notice"] input[type="checkbox"]').check();
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("change-notice")),
    page.locator('form[action="/change-notice"] button[type="submit"]').click(),
  ]);
}
await page.goto(`${base}/v2-clean/tasks?workspace=all&status=open&category=all`);
if ((await page.locator("[data-task-row]").count()) === 0) {
  throw new Error(`No task rows at ${page.url()}: ${(await page.locator("body").innerText()).slice(0, 800)}`);
}
await page.locator("[data-task-row]").first().click();
if (process.env.TASK_CENTER_BASELINE_ONLY === "1") {
  await page.screenshot({ path: path.join(output, "00-before-selected-1440x731.png") });
  await browser.close();
  process.exit(0);
}
await page.screenshot({ path: path.join(output, "01-selected-1440x731.png") });

await page.locator('[data-task-preview-action="open"]').click();
await page.waitForURL(/\/v2-clean\/tasks\/\d+\/detail\?return_context=/);
if ((await page.locator('form[action*="/update"] input[name="title"]').count()) !== 1) throw new Error("Real editable detail did not open");
for (const field of ["work_queue_id", "work_department_id", "work_category_id", "work_subcategory_id", "assigned_team_id", "assigned_to_id"]) {
  if ((await page.locator(`form[action*="/update"] [name="${field}"]`).count()) !== 1) throw new Error(`Detail field missing: ${field}`);
}
await page.screenshot({ path: path.join(output, "02-real-detail-return-context-1440x731.png") });
const returnHref = await page.locator('a:has-text("Voltar ao Centro de Tarefas")').getAttribute("href");
if (!returnHref?.includes("#task-")) throw new Error(`ReturnContext missing selection: ${returnHref}`);
await page.locator('a:has-text("Voltar ao Centro de Tarefas")').click();
await page.waitForURL(/\/v2-clean\/tasks/);

await page.locator('[data-task-create-open]').click();
await page.locator("[data-task-create-dialog]").waitFor({ state: "visible" });
const createReturn = await page.locator('[data-task-create-form] [name="return_url"]').inputValue();
if (!createReturn.includes("workspace=all") || !createReturn.includes("category=all") || !createReturn.includes("open_task=")) {
  throw new Error(`Create ReturnContext incomplete: ${createReturn}`);
}
await page.screenshot({ path: path.join(output, "03-three-models-1440x731.png") });
for (const model of ["request", "information", "task"]) {
  await page.locator(`[data-create-model="${model}"]`).click();
  const recordType = await page.locator('[data-task-create-form] [name="record_type"]').inputValue();
  if (recordType !== model) throw new Error(`Wrong record type for ${model}: ${recordType}`);
  const moreHidden = await page.locator('[data-create-more]').evaluate((element) => element.hidden);
  if ((model === "task") === moreHidden) throw new Error(`Wrong planning fields visibility for ${model}`);
  for (const field of ["work_queue_id", "work_department_id", "work_category_id", "work_subcategory_id", "entity_type", "entity_id", "attachments"]) {
    if ((await page.locator(`[data-task-create-form] [name="${field}"]`).count()) !== 1) throw new Error(`Create field missing: ${field}`);
  }
  await page.screenshot({ path: path.join(output, `04-${model}-1440x731.png`) });
  await page.locator('[data-task-create-back]').click();
}

const geometry = await page.evaluate(() => ({
  width: innerWidth,
  height: innerHeight,
  bodyWidth: document.body.scrollWidth,
  overflow: [...document.querySelectorAll("body *")]
    .filter((element) => {
      const box = element.getBoundingClientRect();
      return box.right > innerWidth + 1 || box.left < -1;
    })
    .map((element) => ({ tag: element.tagName, className: element.className, box: element.getBoundingClientRect().toJSON() })),
}));
fs.writeFileSync(path.join(output, "geometry.json"), JSON.stringify(geometry, null, 2));
if (geometry.width !== 1440 || geometry.height !== 731 || geometry.bodyWidth > 1440 || geometry.overflow.length) {
  throw new Error(`Geometry failed: ${JSON.stringify(geometry)}`);
}
await browser.close();
