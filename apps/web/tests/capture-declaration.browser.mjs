// Synthetic local transport only; no provider calls or physical evidence.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl] = process.argv.slice(2);
const origin = new URL(baseUrl);
assert.ok(["localhost", "127.0.0.1"].includes(origin.hostname));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
const unknown = {
  value: null,
  unit: "mm",
  source: "unknown",
  confirmed: false,
};
const project = {
  id: "capture-project",
  revision_id: "capture-revision",
  goal: "Make a stand",
  inventory_confirmed: false,
  active_version_id: null,
  stocks: ["sheet-a", "sheet-b"].map((id) => ({
    id,
    name: id,
    kind: "sheet",
    material: "cardboard",
    width_mm: unknown,
    height_mm: unknown,
    thickness_mm: unknown,
    remaining_length_mm: unknown,
    condition: "uncertain",
    usable_regions: [],
    image_ids: [],
  })),
};
const base = `/api/projects/${project.id}`;
const media = ["photo-a", "photo-b"].map((id) => ({
  id,
  project_id: project.id,
  content_type: "image/png",
  width_px: 100,
  height_px: 100,
  size_bytes: 68,
  filename: `${id}.png`,
}));
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRCsAAAAASUVORK5CYII=",
  "base64",
);
const requests = [],
  unexpected = [],
  errors = [];
try {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  await context.route("**/*", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (url.origin !== origin.origin) {
      unexpected.push(url.href);
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (
      request.method() === "POST" &&
      url.pathname === `${base}/photo-estimates`
    ) {
      requests.push(request.postDataJSON());
      return route.fulfill({
        status: 422,
        json: { message: "Synthetic measurement rejection" },
      });
    }
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    }
    if (media.some((m) => url.pathname === `${base}/media/${m.id}`))
      return route.fulfill({ contentType: "image/png", body: png });
    const responses = new Map([
      ["/api/provider/status", { configured: false }],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, project],
      [`${base}/media`, { media }],
      [`${base}/plans`, { plans: [] }],
      [`${base}/photo-estimates`, { records: [] }],
      [
        `${base}/recognized-items`,
        {
          project_id: project.id,
          revision: "items-empty",
          items: [],
          problems: [],
        },
      ],
    ]);
    return route.fulfill(
      responses.has(url.pathname)
        ? { json: responses.get(url.pathname) }
        : { status: 503, json: { message: "Outside synthetic scenario" } },
    );
  });
  await page.goto(`${origin.origin}/?project=${project.id}`);
  await page.evaluate(
    (t) => localStorage.setItem("forma.visitor-token", t),
    "synthetic-capture-owner",
  );
  await page
    .getByRole("button", { name: "Open workbench", exact: true })
    .click();
  await page.locator("#material-review-details").evaluate((e) => {
    e.open = true;
  });
  const card = page.locator("#card-sheet-a");
  const check = card.getByRole("checkbox", { name: /This piece is flat/ });
  await check.waitFor();
  assert.equal(await check.isChecked(), false);
  const measure = card.getByRole("button", {
    name: "Measure from photo",
    exact: true,
  });
  await check.check();
  await page.getByLabel("Photo to work on").selectOption("photo-a");
  assert.equal(
    await check.isChecked(),
    false,
    "another photo needs its own declaration",
  );
  await card.getByRole("button", { name: "Draw a box", exact: true }).click();
  const svg = card.locator(".guided-canvas svg");
  await svg.scrollIntoViewIfNeeded();
  const rect = await svg.boundingBox();
  await page.mouse.move(rect.x + rect.width * 0.2, rect.y + rect.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * 0.7, rect.y + rect.height * 0.7);
  await page.mouse.up();
  assert.equal(
    await measure.isDisabled(),
    true,
    "box alone cannot imply capture declarations",
  );
  assert.equal(requests.length, 0);
  await check.check();
  assert.equal(await measure.isEnabled(), true);
  assert.equal(
    await page
      .locator("#card-sheet-b")
      .getByRole("checkbox", { name: /This piece is flat/ })
      .isChecked(),
    false,
    "another piece needs its own declaration",
  );
  await page.locator(".guided-reference").evaluate((e) => {
    e.open = true;
  });
  await page.getByLabel("Line A, measured (mm)", { exact: true }).fill("150");
  await measure.click();
  await page
    .getByText("Synthetic measurement rejection", { exact: true })
    .waitFor();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].media_id, "photo-a");
  assert.equal(requests[0].stock_id, "sheet-a");
  assert.deepEqual(requests[0].capture, {
    shape: "flat",
    same_surface_as_reference: true,
  });
  assert.deepEqual(unexpected, []);
  assert.deepEqual(errors, []);
  console.log(
    "PASS capture declaration: unchecked blocked, checked enabled, independent photo/piece scope, explicit request body",
  );
  await context.close();
} finally {
  await browser.close();
}
