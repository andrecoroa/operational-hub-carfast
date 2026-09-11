import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_CENTER_PREVIEW_URL || "http://127.0.0.1:18766";
const output = path.resolve(
  process.env.TASK_TOOLBAR_EVIDENCE_DIR || "docs/evidence/task-toolbar-responsive/browser"
);
fs.mkdirSync(output, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${base}/login`);
await page.locator('input[name="email"]').fill("executor.preview@carfast.local");
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

const inspect = async () => page.evaluate(() => {
  const box = (selector) => {
    const rect = document.querySelector(selector)?.getBoundingClientRect();
    return rect ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom } : null;
  };
  return {
    viewportWidth: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    toolbar: box(".task-center-approved-toolbar"),
    navigation: box(".task-center-approved-navigation"),
    actions: box(".task-center-approved-toolbar-actions"),
    queues: box(".task-center-queue-chips"),
  };
});

await page.goto(`${base}/v2-clean/tasks?queue=tasks_support`);
const desktop = await inspect();
if (desktop.documentWidth > desktop.viewportWidth) throw new Error(`Desktop overflow: ${JSON.stringify(desktop)}`);
await page.screenshot({ path: path.join(output, "toolbar-1440x900.png"), fullPage: true });

await page.setViewportSize({ width: 373, height: 844 });
await page.reload({ waitUntil: "networkidle" });
const mobile = await inspect();
if (mobile.documentWidth > mobile.viewportWidth) throw new Error(`Mobile overflow: ${JSON.stringify(mobile)}`);
for (const name of ["toolbar", "navigation", "actions", "queues"]) {
  const rect = mobile[name];
  if (!rect || rect.left < 0 || rect.right > mobile.viewportWidth) {
    throw new Error(`Mobile ${name} escapes viewport: ${JSON.stringify(mobile)}`);
  }
}
await page.screenshot({ path: path.join(output, "toolbar-373x844.png"), fullPage: true });

const result = { desktop, mobile };
fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
await browser.close();
