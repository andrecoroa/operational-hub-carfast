import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_PREVIEW_BASE_URL || "http://127.0.0.1:18767";
const email = process.env.TASK_PREVIEW_EMAIL || "queue.preview@carfast.local";
const password = process.env.TASK_PREVIEW_PASSWORD || "PreviewOnly123!";
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
  await second.click();
  const selected = page.locator(`${selector}[aria-selected="true"]`);
  if ((await selected.count()) !== 1) throw new Error(`${grouping}: multiple selections`);
  if (grouping === "flat" && !(await second.evaluate((el) => el.nextElementSibling?.classList.contains("task-inline-preview-row")))) throw new Error("flat: preview not below selected row");
  if (grouping !== "flat" && !(await second.evaluate((el) => el.nextElementSibling?.matches("[data-task-preview]")))) throw new Error(`${grouping}: preview not below selected task`);

  await second.press("Escape");
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

results.flat = await assertSinglePreviewContract("flat");
await page.setViewportSize({ width: 390, height: 844 });
results.case = await assertSinglePreviewContract("case");
results.category = await assertSinglePreviewContract("category");
console.log(JSON.stringify(results));
await browser.close();
