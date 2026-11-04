// Real static synthetic engine bundle, normal browser navigation, no API replay.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, destination] = process.argv.slice(2);
if (!modulePath || !baseUrl || !destination)
  throw Error("Pass Playwright module, URL and screenshot directory");
const origin = new URL(baseUrl);
if (
  !["127.0.0.1", "localhost", "52-0-105-215.sslip.io"].includes(origin.hostname)
)
  throw Error("Unexpected walkthrough origin");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
fs.mkdirSync(destination, { recursive: true });
try {
  for (const width of [1280, 390, 320]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    const errors = [],
      unexpected = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await context.route("**/*", async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.protocol === "blob:") return route.continue();
      if (
        url.origin !== origin.origin ||
        request.method() !== "GET" ||
        url.pathname.startsWith("/api/")
      ) {
        unexpected.push(`${request.method()} ${url.pathname}`);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(`${origin.origin}/walkthrough`);
    await page
      .getByRole("heading", { name: "Your starting point", exact: true })
      .waitFor();
    const stages = page
      .getByRole("navigation", { name: "Pipeline stages" })
      .getByRole("button");
    const count = await stages.count();
    assert(count >= 30);
    assert(
      await page.getByRole("button", { name: "Previous stage" }).isDisabled(),
    );
    await page
      .getByLabel("What would you improve here?")
      .fill(`UX note ${width}`);
    await page.getByRole("button", { name: "Next stage" }).click();
    await page.goBack();
    await page
      .getByRole("heading", { name: "Your starting point", exact: true })
      .waitFor();
    assert.equal(
      await page.getByLabel("What would you improve here?").inputValue(),
      `UX note ${width}`,
    );
    await page.reload();
    assert.equal(
      await page.getByLabel("What would you improve here?").inputValue(),
      `UX note ${width}`,
    );
    for (let index = 0; index < count; index++) {
      await stages.nth(index).click();
      assert.equal(
        await stages.nth(index).getAttribute("aria-current"),
        "step",
      );
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        true,
        `overflow stage ${index} width ${width}`,
      );
    }
    assert(await page.getByRole("button", { name: "Next stage" }).isDisabled());
    await stages.filter({ hasText: "Explore every instruction" }).click();
    const manual = page.getByRole("region", { name: "Assembly manual" });
    await manual.getByRole("img").waitFor();
    for (let index = 1; index < 8; index++)
      await page.getByRole("button", { name: "Next instruction" }).click();
    assert(
      await page.getByRole("button", { name: "Next instruction" }).isDisabled(),
    );
    await page.getByRole("button", { name: "Previous instruction" }).click();
    assert.equal(
      await manual.getByRole("heading", { name: "Step 7 of 8" }).count(),
      1,
    );
    await stages.filter({ hasText: "Explore the assembled shape" }).click();
    const preview = page.getByRole("region", {
      name: "Saved assembly preview",
    });
    await preview.getByRole("img").waitFor();
    const before = await preview
      .locator("polygon")
      .first()
      .getAttribute("points");
    await preview.getByLabel("Rotation").fill("90");
    assert.notEqual(
      await preview.locator("polygon").first().getAttribute("points"),
      before,
    );
    await page.screenshot({
      path: path.join(destination, `assembly-${width}.png`),
      fullPage: true,
    });
    await stages.filter({ hasText: "Final review and Proof" }).click();
    await page.getByText("Read the saved reply", { exact: true }).click();
    await page.screenshot({
      path: path.join(destination, `proof-${width}.png`),
      fullPage: true,
    });
    await page.goto(`${origin.origin}/walkthrough#manual`);
    await page
      .getByRole("heading", { name: "Explore every instruction", exact: true })
      .waitFor();
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      `PASS ${width}px: ${count} stages, back/reload, notes, all manual steps, rotation, deep links, no API/provider calls`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
