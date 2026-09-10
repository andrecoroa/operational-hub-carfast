import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const base = process.env.TASK_CENTER_PREVIEW_URL || "http://127.0.0.1:18766";
const output = path.resolve(process.env.TASK_CENTER_EVIDENCE_DIR || "docs/evidence/task-center-manual-findings");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });

async function login(page) {
  await page.goto(`${base}/login`);
  await page.locator('input[name="email"]').fill("executor.preview@carfast.local");
  await page.locator('input[name="password"]').fill("PreviewOnly123!");
  await page.locator('form[action="/login"] button[type="submit"]').click();
  if (page.url().includes("change-notice")) {
    await page.locator('input[type="checkbox"]').check();
    await page.locator('form[action="/change-notice"] button[type="submit"]').click();
  }
}

const evidence = {};
for (const viewport of [{ width: 1440, height: 731, name: "desktop" }, { width: 390, height: 844, name: "mobile" }]) {
  const page = await browser.newPage({ viewport });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await login(page);
  await page.goto(`${base}/v2-clean/tasks?workspace=all&mine_kind=all&assignment=unassigned&category=all&grouping=flat&task_scope_view=claim&queue=tasks_support&status=open&due=&q=&sort=priority`);
  if ((await page.locator('[data-task-row]').count()) === 0) {
    throw new Error(`No task rows: ${(await page.locator("body").innerText()).slice(0, 1200)}`);
  }
  const row = page.locator('[data-task-row]').first();
  await row.waitFor({ state: "visible" });
  if ((await row.getAttribute("data-can-update")) !== "1") {
    throw new Error(`Synthetic browser user cannot update the selected fixture task`);
  }
  const taskId = await row.getAttribute("data-task-id");
  const initialState = await row.getAttribute("data-state");
  await row.click();
  await page.locator('[data-task-preview-action="state"]').click();
  const state = page.locator('[data-task-state-dialog]');
  await state.waitFor({ state: "visible" });
  const stateContract = await state.evaluate((dialog) => ({
    current: dialog.querySelector('[data-task-current-state]')?.textContent?.trim(),
    destinations: [...dialog.querySelectorAll('[name="status"] option')].map((option) => option.textContent.trim()),
  }));
  if (!stateContract.current || !stateContract.destinations.length) throw new Error(`Ambiguous state editor: ${JSON.stringify(stateContract)}`);
  await page.screenshot({ path: path.join(output, `${viewport.name}-state.png`) });
  await state.locator('[data-task-dialog-cancel]').click();
  await page.locator('[data-task-preview-action="open"]').click();
  const management = page.locator('.clean-task-preview[aria-hidden="false"]');
  await management.waitFor({ state: "visible" });
  const managementContract = await management.evaluate((element) => ({
    summaries: [...element.querySelectorAll('summary')].map((summary) => summary.textContent.trim()),
    priorityVisible: element.querySelector('[name="priority"]')?.checkVisibility(),
    dueVisible: element.querySelector('[name="due_on"]')?.checkVisibility(),
    hiddenPlate: !element.querySelector('[name="plate"]')?.checkVisibility(),
    statusInputs: element.querySelectorAll('[name="status"]').length,
    bodyOverflow: document.body.scrollWidth > innerWidth,
  }));
  if (managementContract.summaries.length < 2 || !managementContract.priorityVisible || !managementContract.dueVisible || !managementContract.hiddenPlate || managementContract.statusInputs || managementContract.bodyOverflow) {
    throw new Error(`Management progressive disclosure failed: ${JSON.stringify(managementContract)}`);
  }
  await page.screenshot({ path: path.join(output, `${viewport.name}-management.png`), fullPage: false });
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    management.locator('button[name="post_action"][value="stay"]').click(),
  ]);
  const stateAfterEdit = await page.locator(`[data-task-row][data-task-id="${taskId}"]`).getAttribute("data-state");
  if (stateAfterEdit !== initialState) throw new Error(`Edit changed state: ${initialState} -> ${stateAfterEdit}`);
  const reopenedManagement = page.locator('.clean-task-preview[aria-hidden="false"]');
  if (await reopenedManagement.count()) {
    await reopenedManagement.locator('[data-task-close]').last().click();
  }

  const candidateIds = await page.locator('[data-task-row]').evaluateAll(rows => rows.map(row => row.dataset.taskId));
  let supportTaskId = null;
  let supportInitialState = null;
  const supportTrigger = page.locator('[data-task-preview-action="support"]');
  for (const candidateId of candidateIds) {
    await page.locator(`[data-task-row][data-task-id="${candidateId}"]`).click();
    if (await supportTrigger.isVisible()) {
      supportTaskId = candidateId;
      supportInitialState = await page.locator(`[data-task-row][data-task-id="${candidateId}"]`).getAttribute("data-state");
      break;
    }
  }
  if (supportTaskId) {
    await supportTrigger.click();
    const supportDialog = page.locator('[data-task-support-dialog]');
    const target = supportDialog.locator('[name="requested_target"] option:not([value=""])').first();
    await supportDialog.locator('[name="requested_target"]').selectOption(await target.getAttribute("value"));
    await supportDialog.locator('[name="message"]').fill(`Prova browser ${viewport.name}`);
    await Promise.all([
      page.waitForLoadState("domcontentloaded"),
      supportDialog.locator('[data-task-support-form] button[type="submit"]').click(),
    ]);
    const restoredManagement = page.locator('.clean-task-preview[aria-hidden="false"]');
    if (await restoredManagement.count()) {
      await restoredManagement.locator('[data-task-close]').last().click();
    }
    const openSupportWorkbench = page.locator('[data-task-preview-action="open"]');
    if (!(await openSupportWorkbench.isVisible())) {
      await page.locator(`[data-task-row][data-task-id="${supportTaskId}"]`).click();
    }
    await openSupportWorkbench.click();
    const supportWorkbench = page.locator('.clean-task-preview[aria-hidden="false"]');
    const responseForm = supportWorkbench.locator('.clean-task-help-request form').first();
    const responseAction = await responseForm.getAttribute("action");
    const returnOptions = await responseForm.locator('[name="next_status"] option').evaluateAll(options => options.map(option => ({ value: option.value, label: option.textContent.trim() })));
    if (!returnOptions.length || returnOptions[0].label.indexOf("Retomar") !== 0) throw new Error(`Missing explicit support return: ${JSON.stringify(returnOptions)}`);
    for (const forged of ["", "support_requested", "planned"]) {
      const rejected = await page.request.post(`${base}${responseAction}`, {
        form: { response: "responded", comment: "Tentativa inválida", next_status: forged, return_url: page.url().replace(base, "") },
        maxRedirects: 0,
      });
      if (rejected.status() !== 303 || !(rejected.headers().location || "").includes("error=")) throw new Error(`Forged support return accepted: ${forged}`);
    }
    await responseForm.locator('[name="next_status"]').selectOption(returnOptions[0].value);
    await responseForm.locator('[name="comment"]').fill("Apoio sintético concluído");
    await Promise.all([
      page.waitForLoadState("domcontentloaded"),
      responseForm.locator('button[name="response"][value="responded"]').click(),
    ]);
    const stateAfterSupport = await page.locator(`[data-task-row][data-task-id="${supportTaskId}"]`).getAttribute("data-state");
    if (stateAfterSupport !== supportInitialState) throw new Error(`Support did not return safely: ${supportInitialState} -> ${stateAfterSupport}`);
    evidence[viewport.name] = { stateContract, managementContract, returnOptions, stateAfterEdit, stateAfterSupport, pageErrors };
  } else {
    throw new Error(`No eligible support target for ${viewport.name}`);
  }

  const finalManagement = page.locator('.clean-task-preview[aria-hidden="false"]');
  if (await finalManagement.count()) {
    await finalManagement.locator('[data-task-close]').last().click();
  }
  const scroll = await page.evaluate(() => ({ top: document.scrollingElement.scrollTop, max: document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight, bodyWidth: document.body.scrollWidth, viewportWidth: innerWidth }));
  await page.mouse.wheel(0, 2000);
  await page.waitForTimeout(150);
  scroll.after = await page.evaluate(() => document.scrollingElement.scrollTop);
  if (scroll.max > 0 && scroll.after <= scroll.top) throw new Error(`Vertical scroll failed: ${JSON.stringify(scroll)}`);
  if (scroll.bodyWidth > scroll.viewportWidth) throw new Error(`Horizontal overflow: ${JSON.stringify(scroll)}`);
  evidence[viewport.name].scroll = scroll;
  if (pageErrors.length) throw new Error(`Browser errors: ${JSON.stringify(pageErrors)}`);
  await page.close();
}

fs.writeFileSync(path.join(output, "runtime.json"), JSON.stringify(evidence, null, 2));
await browser.close();
