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
      reducedMotion: width === 390 ? "no-preference" : "reduce",
    });
    const page = await context.newPage();
    await page.clock.install();
    const errors = [],
      unexpected = [],
      requests = [];
    let mode = "slow";
    let providerDispatches = 0;
    const receipts = new Map();
    let dispatched;
    const dispatchObserved = new Promise((resolve) => {
      dispatched = resolve;
    });
    let releaseProposal;
    const proposalReleased = new Promise((resolve) => {
      releaseProposal = resolve;
    });
    let releaseRejection;
    const rejectionReleased = new Promise((resolve) => {
      releaseRejection = resolve;
    });
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
      [`${base}/photo-estimates`, { records: [] }],
      [
        `${base}/recognized-items`,
        {
          project_id: fixture.project.id,
          revision: "items-empty",
          items: [],
          problems: [],
        },
      ],
      [`${base}/synthesis/research`, { enabled: false }],
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
      if (
        url.pathname === `${base}/measurement-decisions` &&
        route.request().method() === "POST"
      )
        return route.fulfill({
          status: 503,
          json: {
            code: "unavailable",
            message: "Outside offline construction scenario",
          },
        });
      if (url.pathname === `${base}/construction/propose`) {
        const body = route.request().postDataJSON();
        requests.push(body);
        assert.equal(body.expected_revision_id, fixture.project.revision_id);
        assert.equal(body.provider_context_consented, true);
        assert.equal(body.provider_transfer_consented, true);
        assert.equal(body.media_id, "photo-one");
        if (receipts.has(body.idempotency_key)) {
          const receipt = receipts.get(body.idempotency_key);
          return route.fulfill(
            receipt === "unknown"
              ? {
                  status: 409,
                  json: {
                    code: "generation_outcome_unknown",
                    message: "private-server-detail",
                  },
                }
              : { json: { ...receipt, replayed: true } },
          );
        }
        providerDispatches++;
        if (mode === "slow") await proposalReleased;
        if (mode === "delayed") {
          // The server completes the paid request, but navigation loses its
          // response. Recovery must use this completed receipt, never a new key.
          receipts.set(body.idempotency_key, fixture.result);
          dispatched();
          return;
        }
        if (mode === "rejected") {
          await rejectionReleased;
          return route.fulfill({
            status: 502,
            json: {
              code: "invalid_response",
              message: "private-provider-detail",
            },
          });
        }
        if (mode === "uncertain") {
          receipts.set(body.idempotency_key, "unknown");
          return route.fulfill({
            status: 409,
            json: {
              code: "generation_outcome_unknown",
              message: "private-server-detail",
            },
          });
        }
        receipts.set(body.idempotency_key, fixture.result);
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
    await page.getByRole("button", { name: "Detailed entry" }).click();
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
    const proposalRequest = page.waitForRequest("**/construction/propose");
    await ask.click();
    await proposalRequest;
    const cube = panel.locator("[data-cube-state]");
    const solvingCube = panel.locator('[data-cube-state="solving"]');
    await page.clock.fastForward(8_000);
    assert.equal(await cube.count(), 0, "short waits use text status");
    await page.clock.fastForward(2_000);
    await panel.locator('[data-cube-state="waiting"]').waitFor();
    assert.equal(
      await cube.evaluate(
        (element) => element.getAnimations({ subtree: true }).length,
      ),
      width === 390 ? 1 : 0,
    );
    releaseProposal();
    if (width === 390) {
      await solvingCube.waitFor();
      assert.equal(
        await panel
          .getByRole("heading", { name: "Proposed organizer" })
          .isVisible(),
        true,
        "the result renders alongside the solve",
      );
    }
    await panel.getByRole("heading", { name: "Proposed organizer" }).waitFor();
    if (width !== 390) assert.equal(await solvingCube.isVisible(), false);
    await cube.waitFor({ state: "detached" });
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
    const focusIds = await panel
      .locator("polygon[data-step-focus=true]")
      .evaluateAll((nodes) => [
        ...new Set(nodes.map((node) => node.getAttribute("data-part-id"))),
      ]);
    assert.deepEqual(
      focusIds.sort(),
      [...construction.steps[0].part_ids]
        .filter((id) =>
          construction.steps[0].analysis.facets.some(
            (facet) => facet.part_id === id,
          ),
        )
        .sort(),
    );
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
    await panel.getByRole("button", { name: "Start another proposal" }).click();
    mode = "delayed";
    await consent.check();
    await photoConsent.check();
    await ask.click();
    await dispatchObserved;
    const retained = await page.evaluate(() =>
      Object.entries(localStorage).filter(([key]) =>
        key.startsWith("forma-construction-pending-v1:"),
      ),
    );
    assert.equal(retained.length, 1);
    assert.deepEqual(JSON.parse(retained[0][1]).payload, requests[1]);
    assert.ok(!JSON.stringify(retained).includes("offline-owner"));
    await page.reload();
    await page.getByLabel("Owner credential").fill("offline-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    const retry = panel.getByRole("button", {
      name: "Check original proposal request",
    });
    await retry.waitFor();
    await panel
      .getByLabel("Material photo (optional)")
      .locator('option[value="photo-one"]')
      .waitFor({ state: "attached" });
    assert.equal(requests.length, 2, "reload must not dispatch automatically");
    assert.equal(
      await panel.getByLabel("What should the design do?").inputValue(),
      "Hold my pencils.",
    );
    assert.equal(
      await panel.getByLabel("Material photo (optional)").inputValue(),
      "photo-one",
    );
    assert.equal(await consent.isChecked(), false);
    assert.equal(await photoConsent.isChecked(), false);
    assert.equal(await retry.isDisabled(), true);
    assert.equal(
      await panel
        .getByRole("button", { name: "Start another proposal" })
        .count(),
      0,
    );
    await consent.check();
    await photoConsent.check();
    await retry.click();
    await panel.getByRole("heading", { name: "Proposed organizer" }).waitFor();
    assert.equal(await cube.count(), 0, "a quick replay skips the cube");
    assert.deepEqual(
      requests[1],
      requests[2],
      "reload recovers exact paid request payload/key",
    );
    assert.equal(
      providerDispatches,
      2,
      "recovery replays completed receipt without another provider dispatch",
    );

    await panel.getByRole("button", { name: "Start another proposal" }).click();
    mode = "rejected";
    await consent.check();
    await photoConsent.check();
    const rejectedRequest = page.waitForRequest("**/construction/propose");
    await ask.click();
    await rejectedRequest;
    await page.clock.fastForward(10_000);
    await panel.locator('[data-cube-state="waiting"]').waitFor();
    releaseRejection();
    await panel.getByText(/server rejected the model output/).waitFor();
    assert.equal(
      await cube.count(),
      0,
      "a rejection clears the cube immediately",
    );
    assert.ok(!(await panel.innerText()).includes("private-provider-detail"));
    await panel.getByRole("button", { name: "Start another proposal" }).click();
    assert.equal(
      await panel.getByLabel("What should the design do?").isEnabled(),
      true,
    );
    assert.equal(await consent.isChecked(), false);
    mode = "uncertain";
    await consent.check();
    await photoConsent.check();
    await ask.click();
    await panel.getByText(/original provider outcome is unknown/).waitFor();
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
      requests[4],
      requests[5],
      "uncertain retry must preserve exact original payload/key",
    );
    assert.equal(requests.length, 6);
    assert.equal(
      await panel
        .getByRole("button", { name: "Start another proposal" })
        .count(),
      0,
    );
    responses.set(base, {
      ...fixture.project,
      goal: "Changed saved goal",
      revision_id: "new-inventory",
    });
    await page.reload();
    await page.getByLabel("Owner credential").fill("offline-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    await panel.getByText(/retained request belongs to an earlier/).waitFor();
    assert.equal(await retry.isDisabled(), true);
    assert.equal(await consent.isDisabled(), true);
    assert.equal(
      requests.length,
      6,
      "changed context preserves unknown request without automatic replay",
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.ok(
      await panel.evaluate((p) => p.scrollWidth <= p.clientWidth + 1),
      "panel fits viewport",
    );
    await context.close();
    console.log(
      `PASS ${width}px long-wait cube, consent/photo, engine steps/names, camera-only, durable reload recovery, terminal start-over and unknown/stale request blocking; offline replay only`,
    );
  }
} finally {
  await browser.close();
}
