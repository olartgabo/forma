// Offline browser replay; the intercepted response contains hypothetical geometry.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
const origin = new URL(baseUrl);
assert.ok(["127.0.0.1", "localhost"].includes(origin.hostname));
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
fixture.project.inventory_confirmed = false;
fixture.result.candidates[0].estimated_materials = [
  { label: "Cardboard", width_mm: 200, height_mm: 240, thickness_mm: null },
];
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
try {
  const page = await browser.newPage({
    viewport: { width: Number(process.env.VIEWPORT_WIDTH ?? 390), height: 900 },
    reducedMotion: "reduce",
  });
  const base = `/api/projects/${fixture.project.id}`;
  let calls = 0;
  let receiptRows = [],
    lastKey = null,
    authorizationCalls = 0,
    authorizedKey = null,
    previewReads = 0;
  let heldPreview = null;
  let heldMedia = null;
  const unexpectedWrites = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin.origin) return route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (url.pathname === `${base}/media` && heldMedia) await heldMedia;
    if (url.pathname === `${base}/construction/preview`) {
      previewReads++;
      assert.equal(route.request().method(), "GET");
      assert.equal(
        url.searchParams.get("expected_inventory_revision_id"),
        fixture.project.revision_id,
      );
      const saved = structuredClone(fixture.result);
      if (heldPreview) await heldPreview;
      return route.fulfill({ json: saved }).catch(() => undefined);
    }
    if (url.pathname === `${base}/construction/replacement-authorizations`) {
      authorizationCalls++;
      const body = route.request().postDataJSON();
      assert.equal(body.original_idempotency_key, lastKey);
      assert.equal(body.original_digest, "a".repeat(64));
      assert.equal(body.acknowledge_unknown, true);
      authorizedKey = body.replacement_idempotency_key;
      receiptRows[0] = {
        ...receiptRows[0],
        replacement_idempotency_key: authorizedKey,
        replacement_expected_revision_id: fixture.project.revision_id,
      };
      return route.fulfill({
        json: { ...body, project_id: fixture.project.id, replayed: false },
      });
    }
    if (url.pathname === `${base}/construction/propose`) {
      const body = route.request().postDataJSON();
      assert.equal(body.approximate, true);
      assert.equal(body.media_id, "photo-one");
      assert.equal(body.provider_context_consented, true);
      assert.equal(body.provider_transfer_consented, true);
      if (calls === 1)
        assert.equal(body.user_notes, "Use 210 mm width for the cardboard.");
      if (authorizedKey) assert.equal(body.idempotency_key, authorizedKey);
      lastKey = body.idempotency_key;
      if (authorizedKey)
        receiptRows.unshift({
          idempotency_key: authorizedKey,
          digest: "b".repeat(64),
          state: "completed",
          error_code: null,
          replaces_idempotency_key: receiptRows[0].idempotency_key,
        });
      calls++;
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
    const responses = {
      "/api/provider/status": {
        configured: true,
        model: "offline-browser-fixture",
      },
      "/api/projects": { projects: [], next_cursor: null },
      [base]: fixture.project,
      [`${base}/media`]: {
        media: [
          {
            id: "photo-one",
            project_id: fixture.project.id,
            content_type: "image/png",
            byte_count: 100,
            width: 1,
            height: 1,
            created_at: "2026-11-03T00:00:00Z",
            evidence_linked: false,
          },
        ],
      },
      [`${base}/plans`]: { plans: [] },
      [`${base}/construction/receipts`]: { receipts: receiptRows },
    };
    if (route.request().method() === "GET" && responses[url.pathname])
      return route.fulfill({ json: responses[url.pathname] });
    if (route.request().method() !== "GET")
      unexpectedWrites.push(`${route.request().method()} ${url.pathname}`);
    return route.fulfill({
      status: 404,
      json: { code: "not_found", message: "Offline fixture" },
    });
  });
  await page.goto(`${origin.origin}/?project=${fixture.project.id}`);
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  const panel = page.getByRole("region", {
    name: "Create an illustrated concept",
  });
  await panel.waitFor();
  assert.equal(
    await page
      .getByRole("button", { name: "Photo first" })
      .getAttribute("aria-pressed"),
    "true",
  );
  await page.getByRole("button", { name: "Estimate material sizes" }).click();
  await page
    .getByRole("heading", { name: "Review your materials", exact: true })
    .waitFor();
  assert.equal(
    await page.locator(".guided-reference").evaluate((el) => el.open),
    true,
  );
  assert.equal(calls, 0);
  assert.deepEqual(unexpectedWrites, []);
  await page.getByRole("button", { name: "Photo first", exact: true }).click();
  await panel.getByLabel("Choose a material photo").selectOption("photo-one");
  await panel.getByLabel(/Send the saved goal/).check();
  await panel.getByLabel(/Also send the selected/).check();
  await panel
    .getByRole("button", { name: "Ask MetaMuse for shapes and steps" })
    .click();
  await panel.getByText("Review your materials").waitFor();
  assert.match(await panel.innerText(), /Cardboard: 200 x 240 x unknown mm/);
  assert.equal(
    await panel
      .getByRole("img", { name: /Proposed construction geometry/ })
      .count(),
    0,
  );
  await panel.getByLabel(/Use these estimates for my manual/).check();
  const preparation = panel.getByRole("region", {
    name: "Prepare the proposed pieces",
  });
  await preparation.waitFor();
  assert.ok(
    (await preparation
      .locator(".drawing-sheet.construction-preparation-sheet")
      .count()) > 0,
  );
  assert.match(await preparation.innerText(), /200 × 240 mm/);
  assert.ok(
    (await preparation
      .getByRole("img", { name: /Approximate outline/ })
      .count()) > 0,
  );

  await panel
    .getByRole("img", { name: /Proposed construction geometry/ })
    .waitFor();
  await panel.getByRole("button", { name: "Next step" }).click();
  assert.match(await panel.innerText(), /Step 2 of/);
  await panel.getByRole("button", { name: "Start another proposal" }).click();
  await panel
    .getByLabel("What should the design do?")
    .fill("Use 210 mm width for the cardboard.");
  await panel.getByLabel(/Send the saved goal/).check();
  await panel.getByLabel(/Also send the selected/).check();
  await panel
    .getByRole("button", { name: "Ask MetaMuse for shapes and steps" })
    .click();
  await panel.getByText("Review your materials").waitFor();
  assert.equal(
    await panel
      .getByRole("img", { name: /Proposed construction geometry/ })
      .count(),
    0,
  );
  await panel.getByLabel(/Use these estimates for my manual/).check();
  const diagram = panel.getByRole("img", {
    name: /Proposed construction geometry/,
  });
  await diagram.scrollIntoViewIfNeeded();
  assert.equal(calls, 2);
  assert.deepEqual(unexpectedWrites, []);
  // Read-only reload restores the complete manual, retaining conservative review.
  receiptRows = [
    {
      idempotency_key: lastKey,
      digest: "a".repeat(64),
      state: "completed",
      error_code: null,
    },
  ];
  await page.reload();
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  await panel
    .getByText(/Saved proposal restored without a model request/)
    .waitFor();
  assert.equal(calls, 2);
  await panel
    .getByLabel("Review these proposed dimensions for my saved manual.")
    .check();
  const diagrams = panel.getByRole("region", {
    name: "Proposed step diagrams",
  });
  await diagrams.waitFor();
  assert.equal(await diagrams.getByRole("img").count(), 3);
  assert.equal(
    await diagrams.locator(".drawing-sheet.construction-blueprint").count(),
    3,
  );
  const blueprintStyle = await diagrams
    .locator(".construction-blueprint")
    .first()
    .evaluate((el) => ({
      background: getComputedStyle(el).backgroundColor,
      grid: getComputedStyle(el).backgroundImage,
    }));
  assert.equal(blueprintStyle.background, "rgb(22, 91, 189)");
  assert.match(blueprintStyle.grid, /linear-gradient/);
  const focusStyle = await diagrams
    .locator('polygon[data-step-focus="true"]')
    .first()
    .evaluate((el) => ({
      stroke: getComputedStyle(el).stroke,
      width: getComputedStyle(el).strokeWidth,
    }));
  assert.equal(focusStyle.stroke, "rgb(255, 149, 194)");
  assert.equal(focusStyle.width, "4px");
  assert.match(await diagrams.innerText(), /STEP 1 \/ TOP/i);
  const firstPoints =
    fixture.result.candidates[0].construction.steps[0].analysis.facets.flatMap(
      (f) => f.vertices,
    );
  const zSpanMm =
    (Math.max(...firstPoints.map((p) => p.z)) -
      Math.min(...firstPoints.map((p) => p.z))) *
    1000;
  for (const view of ["front", "side"])
    assert.equal(
      await diagrams
        .getByRole("img", { name: new RegExp(`^${view} diagram`) })
        .locator('[data-dimension="height"]')
        .count(),
      Math.round(zSpanMm * 10) > 0 ? 1 : 0,
      "zero-span panels must not gain invented height arrows",
    );
  const currentIds = await panel
    .getByRole("img", { name: /Proposed construction geometry/ })
    .locator("polygon")
    .evaluateAll((nodes) =>
      nodes.map((n) => n.getAttribute("data-part-id")).sort(),
    );
  for (const view of ["top", "front", "side"]) {
    const ids = await diagrams
      .getByRole("img", { name: new RegExp(`^${view} diagram`) })
      .locator("polygon")
      .evaluateAll((nodes) =>
        nodes.map((n) => n.getAttribute("data-part-id")).sort(),
      );
    assert.deepEqual(ids, currentIds);
  }
  await panel.getByRole("button", { name: "Next step" }).click();
  assert.match(await diagrams.innerText(), /proposed bounds/i);
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
    false,
    "blueprint sheets fit the viewport",
  );
  if (process.env.SCREENSHOT_PATH)
    await diagrams.screenshot({ path: process.env.SCREENSHOT_PATH });
  // Metadata may hydrate after an initially restored manual. It must restore
  // again for that context rather than leave the panel permanently blank.
  let releaseMedia;
  heldMedia = new Promise((resolve) => {
    releaseMedia = resolve;
  });
  await page.reload();
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  await panel
    .getByText(/Saved proposal restored without a model request/)
    .waitFor();
  releaseMedia();
  heldMedia = null;
  await panel
    .getByLabel("Choose a material photo")
    .locator('option[value="photo-one"]')
    .waitFor({ state: "attached" });
  await panel
    .getByText(/Saved proposal restored without a model request/)
    .waitFor();
  // Unknown receipt never loads an older saved result. Replacement requires an
  // explicit authorization, then fresh consent and a separately clicked Ask.
  receiptRows = [
    {
      idempotency_key: lastKey,
      digest: "a".repeat(64),
      state: "unknown",
      error_code: "timeout",
    },
  ];
  const readsBefore = previewReads;
  await page.reload();
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  await panel.getByText(/Stored request state: unknown/).waitFor();
  assert.equal(previewReads, readsBefore);
  assert.equal(
    await panel
      .getByRole("img", { name: /Proposed construction geometry/ })
      .count(),
    0,
  );
  await panel
    .getByRole("button", { name: "Authorize a separate paid replacement" })
    .click();
  await panel.getByText(/Replacement identity prepared/).waitFor();
  assert.equal(authorizationCalls, 1);
  assert.equal(calls, 2);
  assert.equal(
    await panel
      .getByRole("button", {
        name: "Ask MetaMuse for the authorized replacement",
      })
      .isDisabled(),
    true,
  );
  const archives = await page.evaluate(() =>
    Object.keys(localStorage)
      .filter((key) => key.includes(":unknown:"))
      .map((key) => localStorage.getItem(key)),
  );
  assert.equal(archives.length, 1);
  assert.equal(
    JSON.parse(archives[0]).payload.idempotency_key,
    receiptRows[0].idempotency_key,
  );
  await panel.getByLabel(/Send the saved goal/).check();
  await panel.getByLabel(/Also send the selected/).check();
  await panel
    .getByRole("button", {
      name: "Ask MetaMuse for the authorized replacement",
    })
    .click();
  await panel.getByText("Review your materials").waitFor();
  assert.equal(calls, 3);
  // A fresh browser restores the completed replacement; its ancestor remains
  // unknown but no longer blocks a separately consented new request.
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  await panel
    .getByText(/Saved proposal restored without a model request/)
    .waitFor();
  assert.equal(
    await panel
      .getByRole("button", { name: "Ask MetaMuse for shapes and steps" })
      .isDisabled(),
    true,
  );
  await panel.getByLabel("Choose a material photo").selectOption("photo-one");
  await panel.getByLabel(/Send the saved goal/).check();
  await panel.getByLabel(/Also send the selected/).check();
  assert.equal(
    await panel
      .getByRole("button", { name: "Ask MetaMuse for shapes and steps" })
      .isDisabled(),
    false,
  );
  assert.equal(calls, 3);
  // A late restore response must not overwrite a newer explicitly generated result.
  let releasePreview;
  heldPreview = new Promise((resolve) => {
    releasePreview = resolve;
  });
  const previewStarted = page.waitForRequest((r) =>
    r.url().includes("/construction/preview"),
  );
  await page.reload();
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  await previewStarted;
  authorizedKey = null;
  fixture.result.candidates[0].title = "Newer proposed assembly";
  await panel.getByLabel("Choose a material photo").selectOption("photo-one");
  await panel.getByLabel(/Send the saved goal/).check();
  await panel.getByLabel(/Also send the selected/).check();
  await panel
    .getByRole("button", { name: "Ask MetaMuse for shapes and steps" })
    .click();
  await panel
    .getByRole("heading", { name: "Newer proposed assembly", exact: true })
    .waitFor();
  releasePreview();
  heldPreview = null;
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  assert.equal(
    await panel
      .getByRole("heading", { name: "Newer proposed assembly", exact: true })
      .count(),
    1,
  );
  assert.equal(calls, 4);
  // A saved active build always exposes its existing manual and repair flow,
  // even when the browser previously selected photo-first entry.
  fixture.project.active_version_id = "active-fixture";
  await page.reload();
  await page.getByLabel("Owner credential").fill("offline-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  await page
    .getByRole("heading", { name: "Review your plan and manual" })
    .waitFor();
  assert.equal(
    await page.getByRole("button", { name: "Photo first" }).isDisabled(),
    true,
  );
  assert.equal(
    await page
      .getByRole("button", { name: "Detailed entry" })
      .getAttribute("aria-pressed"),
    "true",
  );
  assert.equal(
    calls,
    4,
    "opening an active manual dispatches no concept request",
  );
  console.log(
    "Photo-first recovery, diagrams, restore race and explicit replacement replay passed; four intercepted hypothetical requests, no provider calls.",
  );
} finally {
  await browser.close();
}
