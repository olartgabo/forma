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
    viewport: { width: 390, height: 900 },
    reducedMotion: "reduce",
  });
  const base = `/api/projects/${fixture.project.id}`;
  let calls = 0;
  const unexpectedWrites = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin.origin) return route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (url.pathname === `${base}/construction/propose`) {
      const body = route.request().postDataJSON();
      assert.equal(body.approximate, true);
      assert.equal(body.media_id, "photo-one");
      assert.equal(body.provider_context_consented, true);
      assert.equal(body.provider_transfer_consented, true);
      if (calls === 1)
        assert.equal(body.user_notes, "Use 210 mm width for the cardboard.");
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
  if (process.env.SCREENSHOT_PATH)
    await page.screenshot({ path: process.env.SCREENSHOT_PATH });
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
    2,
    "opening an active manual dispatches no concept request",
  );
  console.log(
    "Photo-first browser replay passed; two intercepted hypothetical requests, no provider calls.",
  );
} finally {
  await browser.close();
}
