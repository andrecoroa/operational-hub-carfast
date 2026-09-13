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
  process.env.ADMIN_TABLE_EVIDENCE_DIR || "docs/evidence/admin-table-contract/browser"
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

const routes = [
  ["overview", "/v2-clean/admin/overview"],
  ["setup", "/v2-clean/admin/setup"],
  ["organization", "/v2-clean/admin/organization"],
  ["users", "/v2-clean/admin/users"],
  ["roles", "/v2-clean/admin/roles"],
  ["settings", "/v2-clean/admin/settings"],
  ["operations", "/v2-clean/admin/operations"],
  ["task-process-models", "/v2-clean/admin/task-process-models"],
  ["workshop-models", "/v2-clean/admin/workshop-models"],
  ["integrations", "/v2-clean/admin/integrations"],
  ["security", "/v2-clean/admin/security"],
  ["audit", "/v2-clean/admin/audit"],
  ["evolution", "/v2-clean/admin/evolution"],
  ...["desk", "structure", "proposals", "permissions", "sources", "channels", "templates"]
    .map((view) => [`classification-${view}`, `/v2-clean/admin/work-classification?view=${view}`]),
];
const sizes = [[1440, 900], [1024, 768], [678, 812], [390, 844]];
const screenshotNames = new Set(["roles", "classification-channels"]);
const results = [];

for (const [width, height] of sizes) {
  await page.setViewportSize({ width, height });
  for (const [name, route] of routes) {
    await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
    const evidence = await page.evaluate(() => {
      const visible = (element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const tables = [...document.querySelectorAll(".clean-admin-content table")].filter(visible);
      return {
        viewportWidth: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        tables: tables.map((table) => {
          const region = table.closest(".clean-admin-table-region");
          const hintId = region?.getAttribute("aria-describedby");
          const hint = hintId ? document.getElementById(hintId) : null;
          const rect = region?.getBoundingClientRect();
          const firstCell = table.querySelector("tbody tr > :first-child");
          return {
            columns: table.querySelectorAll("thead th").length,
            region: Boolean(region),
            role: region?.getAttribute("role"),
            tabIndex: region?.tabIndex,
            overflowX: region ? getComputedStyle(region).overflowX : null,
            left: rect ? Math.round(rect.left) : null,
            right: rect ? Math.round(rect.right) : null,
            clientWidth: region?.clientWidth,
            scrollWidth: region?.scrollWidth,
            hintVisible: hint ? visible(hint) : false,
            firstCellPosition: firstCell ? getComputedStyle(firstCell).position : null,
          };
        }),
      };
    });
    if (evidence.documentWidth > evidence.viewportWidth) {
      throw new Error(`Page overflow: ${name} ${width}px ${JSON.stringify(evidence)}`);
    }
    for (const table of evidence.tables) {
      if (!table.region || table.role !== "region" || table.tabIndex !== 0 || table.overflowX !== "auto") {
        throw new Error(`Missing table region: ${name} ${width}px ${JSON.stringify(table)}`);
      }
      if (table.left < 0 || table.right > evidence.viewportWidth + 1) {
        throw new Error(`Table region escapes viewport: ${name} ${width}px ${JSON.stringify(table)}`);
      }
      if (width <= 1024 && (!table.hintVisible || (table.firstCellPosition && table.firstCellPosition !== "sticky"))) {
        throw new Error(`Missing narrow table affordance: ${name} ${width}px ${JSON.stringify(table)}`);
      }
    }
    results.push({ name, width, height, ...evidence });
    if (screenshotNames.has(name)) {
      const firstRegion = page.locator(".clean-admin-table-region").filter({ visible: true }).first();
      if (await firstRegion.count()) await firstRegion.click();
      await page.screenshot({ path: path.join(output, `${name}-${width}x${height}.png`) });
    }
  }
}

fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ pages: results.length, tableChecks: results.reduce((sum, item) => sum + item.tables.length, 0) }));
await browser.close();
