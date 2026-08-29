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
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(error.message));
const runtime = { viewport: { width: 1440, height: 731 }, checks: {} };

async function expectRejected(url) {
  const response = await page.request.get(`${base}${url}`);
  if (![400, 422].includes(response.status())) {
    throw new Error(`Contract-invalid URL was accepted (${response.status()}): ${url}`);
  }
  return response.status();
}

async function expectFocusAfterKeyboard(selector) {
  await page.locator(selector).focus();
  await page.keyboard.press("Enter");
  return page.evaluate(() => ({
    tag: document.activeElement?.tagName,
    name: document.activeElement?.getAttribute("name"),
    action: document.activeElement?.getAttribute("data-task-preview-action"),
  }));
}

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
await page.goto(`${base}/v2-clean/tasks`);
const centerContract = await page.locator("[data-task-center-contract]").evaluate((element) => ({
  queue: element.getAttribute("data-active-queue"),
  view: element.getAttribute("data-active-view"),
  sort: element.getAttribute("data-sort-criterion"),
  direction: element.getAttribute("data-sort-direction"),
}));
if (centerContract.queue !== "tasks_support" || centerContract.view !== "mine") {
  throw new Error(`Unsafe Task Center default: ${JSON.stringify(centerContract)}`);
}
runtime.checks.defaultContract = centerContract;
runtime.checks.aggregationRejected = await expectRejected("/v2-clean/tasks?queue=all&view=mine");
runtime.checks.invalidViewRejected = await expectRejected("/v2-clean/tasks?queue=tasks_support&view=unknown");
runtime.checks.teamToMineRejected = await expectRejected("/v2-clean/tasks?queue=tasks_support&view=mine&preset=team");
runtime.checks.closedRiskRejected = await expectRejected("/v2-clean/tasks?queue=tasks_support&view=mine&status=closed&risk=at_risk");

for (const view of ["mine", "unassigned", "team"]) {
  const control = page.locator(`[data-task-view="${view}"]`);
  await control.focus();
  await page.keyboard.press("Enter");
  await page.waitForLoadState("domcontentloaded");
  const active = await page.locator("[data-task-center-contract]").getAttribute("data-active-view");
  if (active !== view) throw new Error(`View did not persist: expected ${view}, got ${active}`);
}
runtime.checks.viewPersistence = true;
await page.goto(`${base}/v2-clean/tasks?queue=tasks_support&view=mine&status=open&sort=due_on&direction=asc`);
if ((await page.locator("[data-task-row]").count()) === 0) {
  throw new Error(`No task rows at ${page.url()}: ${(await page.locator("body").innerText()).slice(0, 800)}`);
}
await page.screenshot({ path: path.join(output, "01-default-1440x731.png") });
await page.locator("[data-task-row]").first().click();
if (process.env.TASK_CENTER_BASELINE_ONLY === "1") {
  await page.screenshot({ path: path.join(output, "00-before-selected-1440x731.png") });
  await browser.close();
  process.exit(0);
}
await page.screenshot({ path: path.join(output, "01-selected-1440x731.png") });

const workbenchPreflight = await page.evaluate(() => ({
  selectedRows: document.querySelectorAll('[data-task-row][aria-selected="true"]').length,
  workbenchVisible: !!document.querySelector('[data-task-preview]:not(.is-empty)'),
  tabs: document.querySelectorAll('[data-task-workbench-tab]').length,
}));
if (workbenchPreflight.selectedRows !== 1 || !workbenchPreflight.workbenchVisible || workbenchPreflight.tabs !== 3) {
  throw new Error(`Workbench preflight failed: ${JSON.stringify(workbenchPreflight)} errors=${JSON.stringify(pageErrors)}`);
}
if (!page.url().includes('/v2-clean/tasks')) throw new Error(`Workbench left the Task Center: ${page.url()}`);
await page.screenshot({ path: path.join(output, "02-unified-workbench-1440x731.png") });
for (const tab of ["work", "activity", "details"]) {
  const tabControl = page.locator(`[data-task-workbench-tab="${tab}"]`);
  await tabControl.focus();
  await page.keyboard.press("Enter");
  const selected = await tabControl.getAttribute("aria-selected");
  if (selected !== "true") throw new Error(`Workbench tab ${tab} is not keyboard operable`);
}
runtime.checks.keyboard = await page.evaluate(() => ({
  activeTag: document.activeElement?.tagName,
  activeTab: document.activeElement?.getAttribute("data-task-workbench-tab"),
}));
await page.screenshot({ path: path.join(output, "03-tabs-1440x731.png") });

const taskId = await page.locator("[data-task-row]").first().getAttribute("data-task-id");
const emptyComment = await page.request.post(`${base}/v2-clean/tasks/${taskId}/comments`, {
  form: { comment: "   ", return_url: page.url().replace(base, "") },
  maxRedirects: 0,
});
const emptyLocation = emptyComment.headers()["location"] || "";
if (![400, 422].includes(emptyComment.status()) && !(
  emptyComment.status() === 303 && /(comment_required|invalid_comment|error=)/.test(emptyLocation)
)) {
  throw new Error(`Empty comment was accepted: ${emptyComment.status()}`);
}
runtime.checks.emptyComment = { status: emptyComment.status(), location: emptyLocation };

const supportTrigger = page.locator('[data-task-preview-action="support"]');
if (await supportTrigger.count()) {
  runtime.checks.supportFocus = await expectFocusAfterKeyboard('[data-task-preview-action="support"]');
  const dialog = page.locator("[data-task-support-dialog]");
  await dialog.waitFor({ state: "visible" });
  for (const field of ["requested_target", "message", "due_at"]) {
    if ((await dialog.locator(`[name="${field}"]`).count()) !== 1) {
      throw new Error(`Support field missing: ${field}`);
    }
  }
  const firstEligible = dialog.locator('[name="requested_target"] option:not([value=""])').first();
  if (await firstEligible.count()) {
    await dialog.locator('[name="requested_target"]').selectOption(await firstEligible.getAttribute("value"));
    await dialog.locator('[name="message"]').fill("Pedido sintético para prova browser");
    await Promise.all([
      page.waitForLoadState("domcontentloaded"),
      dialog.locator('button[type="submit"]').click(),
    ]);
    if (!page.url().includes("#task-")) throw new Error(`Support lost ReturnContext: ${page.url()}`);
    runtime.checks.supportRequest = true;
  }
}
if (!page.url().includes('#task-')) throw new Error(`Selection context was not preserved: ${page.url()}`);

await page.locator('[data-task-create-open]').click();
await page.locator("[data-task-create-dialog]").waitFor({ state: "visible" });
const createReturn = await page.locator('[data-task-create-form] [name="return_url"]').inputValue();
if (!createReturn.includes("workspace=all") || !createReturn.includes("category=all") || !createReturn.includes("#task-preview-")) {
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
runtime.checks.geometry = geometry;
runtime.checks.pageErrors = pageErrors;
fs.writeFileSync(path.join(output, "runtime-evidence.json"), JSON.stringify(runtime, null, 2));
if (geometry.width !== 1440 || geometry.height !== 731 || geometry.bodyWidth > 1440 || geometry.overflow.length) {
  throw new Error(`Geometry failed: ${JSON.stringify(geometry)}`);
}
if (pageErrors.length) throw new Error(`Browser page errors: ${JSON.stringify(pageErrors)}`);
await browser.close();
