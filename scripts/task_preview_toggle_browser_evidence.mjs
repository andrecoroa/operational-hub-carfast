import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_PREVIEW_BASE_URL || "http://127.0.0.1:18767";
const email = process.env.TASK_PREVIEW_EMAIL || "queue.preview@carfast.local";
const password = process.env.TASK_PREVIEW_PASSWORD || "PreviewOnly123!";
const output = path.resolve(process.env.TASK_PREVIEW_OUTPUT || "docs/evidence/task-preview-toggle/browser");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});

const page = await browser.newPage({ viewport: { width: 1440, height: 731 } });
await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
await page.locator('input[name="email"]').fill(email);
await page.locator('input[name="password"]').fill(password);
await Promise.all([
  page.waitForLoadState("domcontentloaded"),
  page.locator('form[action="/login"] button[type="submit"]').click(),
]);

const query = "workspace=mine&mine_kind=all&assignment=&category=all&task_scope_view=mine&queue=tasks_support&status=open&due=&q=&sort=priority";
const results = {};

async function assertSinglePreviewContract(grouping) {
  await page.goto(`${base}/v2-clean/tasks?${query}&grouping=${grouping}`, {
    waitUntil: "domcontentloaded",
  });
  const selector = grouping === "flat" ? "[data-task-row]" : "[data-group-task]";
  const triggers = page.locator(selector);
  if ((await triggers.count()) < 2) throw new Error(`${grouping}: needs two tasks`);
  const first = triggers.nth(0);
  const second = triggers.nth(1);
  const originalSearch = new URL(page.url()).search;

  await first.click();
  if ((await page.locator("[data-task-preview]").count()) !== 1) throw new Error(`${grouping}: duplicate preview`);
  await first.click();
  if (!(await page.locator("[data-task-preview]").evaluate((el) => el.classList.contains("is-empty")))) throw new Error(`${grouping}: repeated click did not close`);

  await first.click();
  await page.getByRole("button", { name: "Fechar preview" }).click();
  if (!(await first.evaluate((el) => document.activeElement === el))) throw new Error(`${grouping}: explicit close did not restore focus`);

  await first.click();
  await second.click();
  const selected = page.locator(`${selector}[aria-selected="true"]`);
  if ((await selected.count()) !== 1) throw new Error(`${grouping}: multiple selections`);
  if (grouping === "flat" && !(await second.evaluate((el) => el.nextElementSibling?.classList.contains("task-inline-preview-row")))) throw new Error("flat: preview not below selected row");
  if (grouping !== "flat" && !(await second.evaluate((el) => el.nextElementSibling?.matches("[data-task-preview]")))) throw new Error(`${grouping}: preview not below selected task`);

  if (grouping !== "flat") {
    const selectedId = await second.getAttribute("data-group-task");
    await page.reload({ waitUntil: "domcontentloaded" });
    const restored = page.locator(`[data-group-task="${selectedId}"]`);
    if (!(await restored.evaluate((el) => el.nextElementSibling?.matches("[data-task-preview]")))) throw new Error(`${grouping}: hash/session restore mounted preview offscreen`);
  }

  await page.screenshot({ path: path.join(output, `${grouping}-${page.viewportSize().width}x${page.viewportSize().height}.png`), fullPage: true });

  await page.locator(`${selector}[aria-selected="true"]`).press("Escape");
  const state = await page.evaluate(() => ({
    active: document.activeElement?.dataset.taskId || document.activeElement?.dataset.groupTask || null,
    bodyWidth: document.body.scrollWidth,
    width: innerWidth,
    hash: location.hash,
    search: location.search,
  }));
  if (state.hash || state.search !== originalSearch || state.bodyWidth > state.width || !state.active) throw new Error(`${grouping}: close/context/focus/overflow mismatch ${JSON.stringify(state)}`);
  return state;
}

for (const viewport of [{ width: 1440, height: 731 }, { width: 390, height: 844 }]) {
  await page.setViewportSize(viewport);
  for (const grouping of ["flat", "case", "category"]) {
    results[`${grouping}-${viewport.width}x${viewport.height}`] = await assertSinglePreviewContract(grouping);
  }
}
fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results));
await browser.close();
