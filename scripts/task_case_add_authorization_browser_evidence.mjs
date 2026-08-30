import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_CENTER_PREVIEW_URL || "http://127.0.0.1:18766";
const output = path.resolve(
  process.env.TASK_CASE_ADD_EVIDENCE_DIR ||
    "docs/evidence/task-case-add-authorization/browser",
);
fs.mkdirSync(output, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 731 } });
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));

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

const returnQuery =
  "queue=tasks_support&workspace=mine&grouping=case&status=open&sort=priority&q=";
await page.goto(`${base}/v2-clean/tasks?${returnQuery}`);
const caseGroup = page.locator(".task-group").filter({
  hasText: "Dossier sintético de preparação",
});
const before = await caseGroup.locator("[data-group-task]").count();
const addButton = caseGroup.locator('[data-case-flow="add"]');
if (before !== 2 || (await addButton.count()) !== 1) {
  throw new Error(`Authorized add surface mismatch: tasks=${before}`);
}
await addButton.focus();
await page.keyboard.press("Enter");
const dialog = page.locator("[data-task-case-dialog]");
await dialog.waitFor({ state: "visible" });
if ((await page.evaluate(() => document.activeElement?.getAttribute("name"))) !== "task_title") {
  throw new Error("Add-case dialog did not place keyboard focus on task_title");
}
const expectedReturn = `/v2-clean/tasks?${returnQuery}`;
const actualReturn = await dialog.locator('[name="return_url"]').inputValue();
if (actualReturn !== expectedReturn) {
  throw new Error(`ReturnContext mismatch: ${actualReturn}`);
}
await dialog.locator('[name="task_title"]').fill("Tarefa adicionada pelo browser sintético");
await Promise.all([
  page.waitForLoadState("domcontentloaded"),
  dialog.getByRole("button", { name: "Confirmar", exact: true }).click(),
]);
if (!page.url().includes("case_updated=") || !page.url().includes("grouping=case")) {
  throw new Error(`Authorized POST lost context: ${page.url()}`);
}
const afterGroup = page.locator(".task-group").filter({
  hasText: "Dossier sintético de preparação",
});
const after = await afterGroup.locator("[data-group-task]").count();
if (after !== 3) throw new Error(`Expected 3 case tasks after add, got ${after}`);

const desktop = await page.evaluate(() => ({
  width: innerWidth,
  height: innerHeight,
  bodyWidth: document.body.scrollWidth,
  uncontainedOverflow: [...document.querySelectorAll("body *")]
    .filter((element) => {
      if (!(element instanceof HTMLElement) || element.offsetParent === null) return false;
      const box = element.getBoundingClientRect();
      if (box.left >= -1 && box.right <= innerWidth + 1) return false;
      let ancestor = element.parentElement;
      while (ancestor && ancestor !== document.body) {
        const style = getComputedStyle(ancestor);
        const clip = ["auto", "scroll", "hidden", "clip"].includes(style.overflowX);
        if (clip) {
          const parentBox = ancestor.getBoundingClientRect();
          if (box.left < parentBox.left - 1 || box.right > parentBox.right + 1) return false;
        }
        ancestor = ancestor.parentElement;
      }
      return true;
    })
    .map((element) => ({
      tag: element.tagName,
      className: typeof element.className === "string" ? element.className : "",
      left: Math.round(element.getBoundingClientRect().left),
      right: Math.round(element.getBoundingClientRect().right),
    })),
}));
if (
  desktop.width !== 1440 || desktop.height !== 731 || desktop.bodyWidth > 1440 ||
  desktop.uncontainedOverflow.length
) {
  throw new Error(`Desktop geometry failed: ${JSON.stringify(desktop)}`);
}
await page.screenshot({
  path: path.join(output, "case-add-1440x731.png"),
  fullPage: true,
});

await page.setViewportSize({ width: 390, height: 844 });
await page.reload({ waitUntil: "networkidle" });
const mobile = await page.evaluate(() => ({
  width: innerWidth,
  height: innerHeight,
  bodyWidth: document.body.scrollWidth,
  uncontainedOverflow: [...document.querySelectorAll("body *")]
    .filter((element) => {
      if (!(element instanceof HTMLElement) || element.offsetParent === null) return false;
      const box = element.getBoundingClientRect();
      if (box.left >= -1 && box.right <= innerWidth + 1) return false;
      let ancestor = element.parentElement;
      while (ancestor && ancestor !== document.body) {
        const style = getComputedStyle(ancestor);
        if (["auto", "scroll", "hidden", "clip"].includes(style.overflowX)) return false;
        ancestor = ancestor.parentElement;
      }
      return true;
    }).length,
}));
if (mobile.bodyWidth > mobile.width || mobile.uncontainedOverflow) {
  throw new Error(`Mobile overflow: ${JSON.stringify(mobile)}`);
}
if ((await page.locator('[data-case-flow="add"]').count()) !== 1) {
  throw new Error("Authorized add surface disappeared on mobile");
}
await page.screenshot({
  path: path.join(output, "case-add-390x844.png"),
  fullPage: true,
});

if (pageErrors.length) throw new Error(`Browser errors: ${JSON.stringify(pageErrors)}`);
const result = { before, after, returnContext: actualReturn, desktop, mobile, pageErrors };
fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
await browser.close();
