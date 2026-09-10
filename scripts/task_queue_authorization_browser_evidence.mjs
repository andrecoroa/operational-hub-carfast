import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_CENTER_PREVIEW_URL || "http://127.0.0.1:18766";
const output = path.resolve(
  process.env.TASK_QUEUE_EVIDENCE_DIR || "docs/evidence/task-queue-authorization/browser"
);
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 731 } });
await page.goto(`${base}/login`);
await page.locator('input[name="email"]').fill("queue.preview@carfast.local");
await page.locator('input[name="password"]').fill("PreviewOnly123!");
await Promise.all([
  page.waitForLoadState("domcontentloaded"),
  page.locator('form[action="/login"] button[type="submit"]').click(),
]);
if (page.url().includes("change-notice")) {
  await page.locator('form[action="/change-notice"] input[type="checkbox"]').check();
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("change-notice")),
    page.locator('form[action="/change-notice"] button[type="submit"]').click(),
  ]);
}
await page.goto(`${base}/v2-clean/tasks?queue=tasks_support&grouping=case`);
const queueOptions = await page.locator('[data-task-queue] option').allTextContents();
const readonlyQueue = await page.locator('.task-filter-readonly').allTextContents();
if (queueOptions.length && JSON.stringify(queueOptions) !== JSON.stringify(["Tarefas e Suporte"])) {
  throw new Error(`Unexpected queue options: ${JSON.stringify(queueOptions)}`);
}
if (!queueOptions.length && JSON.stringify(readonlyQueue) !== JSON.stringify(["Tarefas e Suporte"])) {
  throw new Error(`Unexpected read-only queue: ${JSON.stringify(readonlyQueue)}`);
}
if ((await page.locator('[data-grouping-mode]').count()) !== 3) {
  throw new Error("Cases regression: grouping controls missing");
}
const forged = await page.request.get(`${base}/v2-clean/tasks?queue=administration`, {
  maxRedirects: 0,
});
const legacyForged = await page.request.get(`${base}/v2-clean/tasks?queue=audit`, {
  maxRedirects: 0,
});
if (forged.status() !== 403 || legacyForged.status() !== 403) {
  throw new Error(`Forged queues not rejected: ${forged.status()}/${legacyForged.status()}`);
}
const desktop = await page.evaluate(() => ({
  width: innerWidth, bodyWidth: document.body.scrollWidth,
  activeQueue: document.querySelector('[data-task-center-contract]')?.dataset.activeQueue,
}));
if (desktop.activeQueue !== "tasks_support" || desktop.bodyWidth > desktop.width) {
  throw new Error(`Desktop contract failed: ${JSON.stringify(desktop)}`);
}
await page.screenshot({ path: path.join(output, "queue-operator-1440x731.png"), fullPage: true });
await page.setViewportSize({ width: 390, height: 844 });
await page.reload({ waitUntil: "networkidle" });
const mobile = await page.evaluate(() => ({ width: innerWidth, bodyWidth: document.body.scrollWidth }));
if (mobile.bodyWidth > mobile.width) throw new Error(`Mobile overflow: ${JSON.stringify(mobile)}`);
await page.screenshot({ path: path.join(output, "queue-operator-390x844.png"), fullPage: true });
const result = { queueOptions, readonlyQueue, forged: forged.status(), legacyForged: legacyForged.status(), desktop, mobile };
fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
await browser.close();
