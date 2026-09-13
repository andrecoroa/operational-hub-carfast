import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const playwrightPackage = process.env.CARFAST_BROWSER_NODE_MODULES
  ? path.join(process.env.CARFAST_BROWSER_NODE_MODULES, "playwright")
  : "playwright";
const { chromium } = require(playwrightPackage);
const base = process.env.ADMIN_PREVIEW_URL || "http://localhost:18766";
const output = path.resolve(
  process.env.ADMIN_SHELL_EVIDENCE_DIR || "docs/evidence/admin-responsive-shell/browser"
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
  const acknowledgement = page.locator('form[action="/change-notice"] input[type="checkbox"]');
  if (await acknowledgement.count()) await acknowledgement.check();
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("change-notice")),
    page.locator('form[action="/change-notice"] button[type="submit"]').click(),
  ]);
}

const cases = [
  ["overview", "/v2-clean/admin/overview"],
  ["roles", "/v2-clean/admin/roles"],
  ["channels", "/v2-clean/admin/work-classification?view=channels"],
];
const sizes = [
  [1440, 900],
  [1024, 768],
  [678, 812],
  [390, 844],
];
const results = [];

for (const [width, height] of sizes) {
  await page.setViewportSize({ width, height });
  for (const [name, route] of cases) {
    await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
    const geometry = await page.evaluate(() => {
      const measure = (selector) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return {
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          clientHeight: element.clientHeight,
          scrollHeight: element.scrollHeight,
          overflowX: style.overflowX,
          overflowY: style.overflowY,
        };
      };
      return {
        viewportWidth: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        masterDetail: measure(".clean-admin-master-detail"),
        master: measure(".clean-admin-master"),
        detail: measure(".clean-admin-detail"),
        activeView: measure(".clean-work-admin-view:not([hidden])"),
      };
    });
    if (geometry.documentWidth > geometry.viewportWidth) {
      throw new Error(`Horizontal page overflow: ${name} ${width}px ${JSON.stringify(geometry)}`);
    }
    if (geometry.detail?.overflowY !== "visible") {
      throw new Error(`Nested detail scroll: ${name} ${width}px ${JSON.stringify(geometry)}`);
    }
    if (geometry.activeView && geometry.activeView.overflowY !== "visible") {
      throw new Error(`Nested classification scroll: ${name} ${width}px ${JSON.stringify(geometry)}`);
    }
    if (width <= 1024 && geometry.master && geometry.detail) {
      if (Math.abs(geometry.master.left - geometry.detail.left) > 2) {
        throw new Error(`Master/detail did not collapse: ${name} ${width}px ${JSON.stringify(geometry)}`);
      }
      if (geometry.detail.width < geometry.masterDetail.width - 2) {
        throw new Error(`Detail does not use available width: ${name} ${width}px ${JSON.stringify(geometry)}`);
      }
    }
    results.push({ name, width, height, ...geometry });
    await page.screenshot({
      path: path.join(output, `${name}-${width}x${height}.png`),
      fullPage: true,
    });
  }
}

fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results));
await browser.close();
