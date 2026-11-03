// Offline UI replay of actual engine-generated geometry. Every API is intercepted;
// no provider calls or physical observations are made.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
const origin = new URL(baseUrl);
assert.ok(["127.0.0.1", "localhost"].includes(origin.hostname));
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
    const errors = [],
      unexpected = [],
      requests = [];
    let mode = "success";
    page.on("pageerror", (e) => errors.push(e.message));
    const base = `/api/projects/${fixture.project.id}`;
    const photo = {
      id: "photo-one",
      project_id: fixture.project.id,
      content_type: "image/png",
      byte_count: 100,
      width: 1,
      height: 1,
      created_at: "2026-11-03T00:00:00Z",
      evidence_linked: false,
    };
    const responses = new Map([
      [
        "/api/provider/status",
        { configured: true, model: "offline-browser-fixture" },
      ],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, fixture.project],
      [`${base}/media`, { media: [photo] }],
      [`${base}/plans`, { plans: [] }],
      [
        `${base}/designs/readiness`,
        {
          project_id: fixture.project.id,
          inventory_revision_id: fixture.project.revision_id,
          inventory_confirmed: true,
          status: "needs_input",
          missing_inputs: ["Measure materials"],
          blockers: [],
        },
      ],
    ]);
    await context.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin.origin) {
        unexpected.push("external request");
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname === `${base}/construction/propose`) {
        const body = route.request().postDataJSON();
        requests.push(body);
        assert.equal(body.expected_revision_id, fixture.project.revision_id);
        assert.equal(body.provider_context_consented, true);
        assert.equal(body.provider_transfer_consented, true);
        assert.equal(body.media_id, "photo-one");
        if (mode === "uncertain")
          return route.fulfill({
            status: 409,
            json: {
              code: "generation_outcome_unknown",
              message: "private-server-detail",
            },
          });
        return route.fulfill({ json: fixture.result });
      }
      if (url.pathname === `${base}/media/photo-one`)
        return route.fulfill({
          contentType: "image/png",
          body: Buffer.from(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
            "base64",
          ),
        });
      if (route.request().method() === "GET" && responses.has(url.pathname))
        return route.fulfill({ json: responses.get(url.pathname) });
      unexpected.push(`${route.request().method()} ${url.pathname}`);
      return route.abort();
    });
    await page.goto(`${origin.origin}/?project=${fixture.project.id}`);
    await page.getByLabel("Owner credential").fill("offline-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    const panel = page.getByRole("region", {
      name: "Invent with my materials",
    });
    await panel.waitFor();
    const measurements = panel.getByRole("group", {
      name: "Saved material measurements",
    });
    assert.match(await measurements.innerText(), /sheet-one/);
    assert.match(await measurements.innerText(), /Thickness: missing/);
    assert.match(await measurements.innerText(), /then save the inventory/);
    const ask = panel.getByRole("button", {
      name: "Ask MetaMuse for shapes and steps",
    });
    assert.equal(await ask.isDisabled(), true);
    await panel
      .getByLabel("What should the design do?")
      .fill("Hold my pencils.");
    await panel
      .getByLabel("Material photo (optional)")
      .selectOption("photo-one");
    const consent = panel.getByLabel(/Send the saved goal/),
      photoConsent = panel.getByLabel(/Also send the selected/);
    await consent.check();
    assert.equal(await ask.isDisabled(), true);
    await photoConsent.check();
    assert.equal(await ask.isEnabled(), true);
    await ask.click();
    await panel.getByRole("heading", { name: "Proposed organizer" }).waitFor();
    assert.equal(requests.length, 1);
    assert.equal(await consent.isChecked(), false);
    assert.equal(await photoConsent.isChecked(), false);
    assert.match(await panel.innerText(), /Measure the sheet thickness/);
    const construction = fixture.result.candidates[0].construction;
    assert.match(await panel.innerText(), /Used in a later step/);
    for (const predicate of construction.steps[0].unresolved_predicates) {
      const notes = panel.getByRole("note", {
        name: "Unresolved checks for this step",
      });
      assert.equal(await notes.isVisible(), true);
      assert.ok((await notes.innerText()).includes(predicate));
    }
    await panel.getByRole("button", { name: "Next step" }).click();
    const stepSelect = panel.getByLabel("Choose a proposed step");
    assert.equal(await stepSelect.inputValue(), "1");
    await stepSelect.selectOption(String(construction.steps.length - 1));
    assert.equal(
      await panel.getByRole("button", { name: "Next step" }).isDisabled(),
      true,
    );
    await stepSelect.selectOption("1");
    await panel.getByLabel("Construction view angle").fill("180");
    assert.equal(
      requests.length,
      1,
      "stage and camera navigation never invokes the model",
    );
    assert.match(await panel.innerText(), /<img src=x onerror=/);
    assert.equal(await panel.locator("img").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    const ids = fixture.result.candidates[0].construction.piece_catalog.map(
      (p) => p.reference,
    );
    for (const id of ids) assert.ok((await panel.innerText()).includes(id));
    if (process.env.SCREENSHOT_DIR)
      await panel.screenshot({
        path: `${process.env.SCREENSHOT_DIR}/muse-construction-${width}.png`,
      });
    mode = "uncertain";
    await consent.check();
    await photoConsent.check();
    await ask.click();
    const retry = panel.getByRole("button", {
      name: "Check original proposal request",
    });
    await retry.waitFor();
    assert.match(await panel.innerText(), /provider outcome is unknown/);
    assert.ok(!(await panel.innerText()).includes("private-server-detail"));
    assert.equal(
      await panel.getByLabel("What should the design do?").isDisabled(),
      true,
    );
    assert.equal(await retry.isDisabled(), true);
    await consent.check();
    await photoConsent.check();
    await retry.click();
    await page.waitForFunction(() =>
      document.body.textContent.includes("provider outcome is unknown"),
    );
    assert.deepEqual(
      requests[1],
      requests[2],
      "uncertain retry must preserve exact original payload/key",
    );
    assert.equal(requests.length, 3);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.ok(
      await panel.evaluate((p) => p.scrollWidth <= p.clientWidth + 1),
      "panel fits viewport",
    );
    await context.close();
    console.log(
      `PASS ${width}px consent/photo, engine steps/names, camera-only, unknown outcome original-key retry; offline replay only`,
    );
  }
} finally {
  await browser.close();
}
