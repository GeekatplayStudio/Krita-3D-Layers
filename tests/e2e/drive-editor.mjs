// Drives a 3D editor page that the plugin opened in a running Krita (manual end-to-end test).
// Start Krita with G3D_TEST_URL_FILE=<file>; the plugin then writes each page's address to
// that file instead of opening a browser. This script opens the newest address, waits for
// the model, optionally turns it, takes a screenshot and clicks the OK button.
//
//   node tests/e2e/drive-editor.mjs <url file> <screenshot.png> [turn degrees] [--cancel]
//   (env MATCH=1 clicks "Match document", PRESET="Golden Hour" picks a light preset)
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";

const [file, shot, turn] = process.argv.slice(2);
const url = readFileSync(file, "utf8").trim().split(/\r?\n/).pop();
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1360, height: 800 }, deviceScaleFactor: 1.5 });
page.on("pageerror", (e) => console.error(`page error: ${e.message}`));
await page.goto(url);
if (url.includes("tasks.html")) {
    await page.getByTestId("task-result").waitFor({ timeout: 240_000 });
    console.log(await page.getByTestId("task-result").innerText());
    await page.screenshot({ path: shot });
    await browser.close();
    process.exit(0);
}
await page.waitForFunction(() => !document.querySelector('[data-testid="editor-ok"]')?.hasAttribute("disabled"), null, { timeout: 180_000 });
// MATCH=1: render at the document's size; PRESET=<light preset name>.
if (process.env.MATCH) await page.getByRole("button", { name: /Match document/ }).click();
if (turn) await page.getByTestId("rotate-y").fill(turn);
if (process.env.PRESET) await page.getByRole("button", { name: process.env.PRESET }).click();
await page.waitForTimeout(2500);
const doc = await page.evaluate(() => ({ below: !!document.querySelector('[data-testid="doc-below"]'), above: !!document.querySelector('[data-testid="doc-above"]'), hint: document.querySelector('[data-testid="document-hint"]')?.textContent ?? null }));
console.log("document view:", JSON.stringify(doc));
await page.screenshot({ path: shot });
if (process.argv.includes("--cancel")) await page.getByRole("button", { name: "Cancel" }).click();
else await page.getByTestId("editor-ok").click();
await page.getByTestId("finished").waitFor({ timeout: 180_000 });
console.log("editor:", await page.getByTestId("finished").innerText());
await browser.close();
