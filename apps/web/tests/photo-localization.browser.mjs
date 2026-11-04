// Actual API fixture plus explicit failure injection. No provider/physical calls.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const [modulePath, baseUrl, fixturePath, screenshotPath] =
  process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw Error("Pass Playwright module, local URL and API fixture");
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1"].includes(origin.hostname))
  throw Error("Local server required");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
try {
  for (const width of [390, 1280]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    const unexpected = [],
      errors = [],
      requests = [];
    let mode = "success",
      shown = fixture.project;
    page.on("pageerror", (e) => errors.push(e.message));
    const base = `/api/projects/${shown.id}`;
    await context.route("**/*", async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== origin.origin) {
        unexpected.push(url.origin);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname !== "/api/provider/status")
        assert.equal(req.headers().authorization, "Bearer synthetic-owner");
      if (url.pathname === `${base}/photo-localizations`) {
        assert.equal(req.method(), "POST");
        const body = req.postDataJSON();
        requests.push(body);
        assert.equal(body.media_id, fixture.photo.id);
        assert.equal(body.provider_transfer_consented, true);
        if (mode === "lost") return route.abort("failed");
        if (mode === "unknown")
          return route.fulfill({
            status: 409,
            json: {
              code: "generation_outcome_unknown",
              message:
                "SAM outcome unknown. Reconcile it before another request.",
            },
          });
        if (mode === "invalid")
          return route.fulfill({
            json: {
              ...fixture.result,
              boxes: [{ ...fixture.result.boxes[0], width: 999 }],
            },
          });
        if (mode === "empty")
          return route.fulfill({ json: { ...fixture.result, boxes: [] } });
        return route.fulfill({
          json: { ...fixture.result, replayed: mode === "replay" },
        });
      }
      if (req.method() !== "GET") {
        unexpected.push(`${req.method()} ${url.pathname}`);
        return route.abort();
      }
      if (url.pathname === `${base}/media/${fixture.photo.id}`)
        return route.fulfill({
          contentType: "image/png",
          body: Buffer.from(fixture.image_base64, "base64"),
        });
      const reads = new Map([
        ["/api/provider/status", { configured: false }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, shown],
        [`${base}/media`, { media: [fixture.photo] }],
        [`${base}/plans`, { plans: [] }],
        [`${base}/designs/readiness`, fixture.readiness],
      ]);
      if (!reads.has(url.pathname)) {
        unexpected.push(url.pathname);
        return route.fulfill({ status: 500, json: { code: "unexpected" } });
      }
      return route.fulfill({ json: reads.get(url.pathname) });
    });
    const panel = () =>
      page.getByRole("region", { name: "Find a material in your photo" });
    async function connect() {
      await page.goto(`${origin.origin}/?project=${shown.id}`);
      await page.getByLabel("Owner credential").fill("synthetic-owner");
      await page
        .getByRole("button", { name: "Open workbench", exact: true })
        .click();
      await panel().waitFor();
    }
    async function prepare() {
      await panel()
        .getByLabel("Photo for localization")
        .selectOption(fixture.photo.id);
      await panel()
        .getByLabel("Material or object name")
        .fill("cardboard sheet");
      await panel()
        .getByLabel(/Send this selected photo/)
        .check();
    }
    await connect();
    await prepare();
    assert.equal(requests.length, 0);
    await panel()
      .getByRole("button", { name: "Find this material in photo", exact: true })
      .click();
    await panel()
      .getByRole("button", { name: "Select cardboard sheet region 1" })
      .click();
    await panel()
      .getByLabel("I reviewed this photo region and its label")
      .check();
    await panel()
      .getByRole("status")
      .filter({ hasText: "Local photo reference" })
      .waitFor();
    assert.equal(await panel().locator("svg rect").getAttribute("x"), "80");
    await panel().getByLabel("x1", { exact: true }).fill("90");
    assert.equal(
      await panel()
        .getByLabel("I reviewed this photo region and its label")
        .isChecked(),
      false,
    );
    await panel()
      .getByLabel("I reviewed this photo region and its label")
      .check();
    if (width === 1280 && screenshotPath) {
      await panel().scrollIntoViewIfNeeded();
      await panel().screenshot({ path: screenshotPath });
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth + 1,
    );
    assert.equal(overflow, false, `page overflow ${width}`);
    await panel().getByLabel("Material or object name").fill("tape");
    assert.equal(await panel().locator("svg rect").count(), 0);
    await panel().getByRole("button", { name: "Adjust a manual box" }).click();
    assert.equal(await panel().locator("svg rect").count(), 1);
    assert.equal(requests.length, 1, "manual box never calls provider");
    // Lost completed response: durable exact body survives reload and is explicitly replayed.
    await panel().getByLabel("Material or object name").fill("cardboard sheet");
    await panel()
      .getByLabel(/Send this selected photo/)
      .check();
    mode = "lost";
    await panel()
      .getByRole("button", { name: "Find this material in photo", exact: true })
      .click();
    await panel().getByRole("alert").waitFor();
    const lost = requests.at(-1);
    assert.equal(
      await panel().getByLabel("Material or object name").isDisabled(),
      true,
    );
    await connect();
    await panel()
      .getByRole("button", { name: "Check same SAM request" })
      .waitFor();
    assert.equal(requests.length, 2, "reload must not auto-dispatch");
    mode = "replay";
    await panel()
      .getByRole("button", { name: "Check same SAM request" })
      .click();
    await panel()
      .getByText(/Recovered saved SAM response/)
      .waitFor();
    assert.deepEqual(requests.at(-1), lost);
    // Invalid successful envelope also retains exact body; unknown outcomes remain locked.
    await panel()
      .getByLabel(/Send this selected photo/)
      .check();
    mode = "invalid";
    await panel()
      .getByRole("button", { name: "Find this material in photo", exact: true })
      .click();
    await panel().getByRole("alert").waitFor();
    const invalid = requests.at(-1);
    mode = "unknown";
    await panel()
      .getByRole("button", { name: "Check same SAM request" })
      .click();
    await panel()
      .getByText(/SAM outcome unknown/)
      .waitFor();
    assert.deepEqual(requests.at(-1), invalid);
    assert.equal(
      await panel()
        .getByRole("button", { name: "Prepare a new request" })
        .count(),
      0,
    );
    // The pending receipt resolves against its original revision, never current actions.
    shown = { ...shown, revision_id: "revision-changed" };
    await connect();
    mode = "replay";
    await panel()
      .getByRole("button", { name: "Check same SAM request" })
      .click();
    await panel()
      .getByText(/Recovered historical SAM response/)
      .waitFor();
    assert.deepEqual(requests.at(-1), invalid);
    assert.equal(
      await panel()
        .getByRole("button", { name: /Select cardboard/ })
        .count(),
      0,
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      `PASS ${width}px: selection, manual correction, no automatic calls, exact lost-response/reload recovery, invalid/unknown receipts, historical suppression; no physical writes`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
