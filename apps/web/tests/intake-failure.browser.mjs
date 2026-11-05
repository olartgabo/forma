// Synthetic intercepted responses only; no provider requests.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const [modulePath, baseUrl] = process.argv.slice(2);
const origin = new URL(baseUrl);
assert.ok(["127.0.0.1", "localhost"].includes(origin.hostname));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
const project = {
  id: "intake-failure-project",
  revision_id: "revision-a",
  goal: "Make a stand",
  stocks: [],
  inventory_confirmed: false,
  active_version_id: null,
};
const base = `/api/projects/${project.id}`;
const media = ["photo-a", "photo-b"].map((id) => ({
  id,
  project_id: project.id,
  content_type: "image/png",
  byte_count: 68,
  width_px: 1,
  height_px: 1,
}));
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC0lEQVR42mP8/x8AAwMCAO+aRCsAAAAASUVORK5CYII=",
  "base64",
);
const diagnostics = {
  reason: "invalid_schema",
  model: "muse-spark-test",
  elapsed_ms: 1234,
  usage: { model_calls: 1, input_tokens: 2200, output_tokens: 2048 },
};
let calls = 0,
  mode = "failure",
  release;
const unexpected = [],
  errors = [];
try {
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on("pageerror", (error) => errors.push(error.message));
  await context.route("**/*", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (url.origin !== origin.origin) {
      unexpected.push(url.origin);
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (url.pathname === `${base}/intake`) {
      calls++;
      const body = request.postDataJSON();
      assert.equal(body.provider_transfer_consented, true);
      if (mode === "held")
        await new Promise((resolve) => {
          release = resolve;
        });
      if (mode === "success")
        return route.fulfill({
          json: {
            project_id: project.id,
            revision_id: project.revision_id,
            media_id: body.media_id,
            observation: {
              labels: ["cardboard"],
              items: [],
              questions: [],
              measurement_source: "unknown",
            },
            diagnostics: {
              status: "ok",
              model: "muse-spark-test",
              elapsed_ms: 1234,
              usage: diagnostics.usage,
            },
          },
        });
      return route.fulfill({
        status: 502,
        json: {
          code: "invalid_response",
          message: "PRIVATE_PROVIDER_CONTENT",
          diagnostics,
        },
      });
    }
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    }
    if (media.some((photo) => url.pathname === `${base}/media/${photo.id}`))
      return route.fulfill({ contentType: "image/png", body: png });
    const responses = new Map([
      ["/api/provider/status", { configured: true, model: "muse-spark-test" }],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, project],
      [`${base}/media`, { media }],
      [`${base}/plans`, { plans: [] }],
      [`${base}/photo-estimates`, { records: [] }],
      [
        `${base}/recognized-items`,
        {
          project_id: project.id,
          revision: "items-a",
          items: [],
          problems: [],
        },
      ],
    ]);
    return route.fulfill(
      responses.has(url.pathname)
        ? { json: responses.get(url.pathname) }
        : { status: 503, json: { code: "unavailable" } },
    );
  });
  await page.goto(`${origin.origin}/?project=${project.id}`);
  await page.evaluate(
    (t) => localStorage.setItem("forma.visitor-token", t),
    "synthetic-intake-owner",
  );
  await page
    .getByRole("button", { name: "Open workbench", exact: true })
    .click();
  const guided = page.locator(".guided-intake");
  const readonly = page.locator('section[aria-labelledby="muse-intake-title"]');
  await readonly
    .getByLabel("Saved photo", { exact: true })
    .selectOption("photo-a");
  await readonly.getByRole("checkbox").check();
  await readonly
    .getByRole("button", { name: "Ask Muse about this photo", exact: true })
    .click();
  await readonly
    .getByRole("alert")
    .filter({ hasText: /missing required information/ })
    .waitFor();
  await readonly.getByText(/input tokens: 2,200/i).waitFor();
  assert.equal(await readonly.getByRole("checkbox").isChecked(), false);
  await readonly
    .getByLabel("Saved photo", { exact: true })
    .selectOption("photo-b");
  assert.equal(await readonly.getByText(/input tokens: 2,200/i).count(), 0);
  const consent = guided.getByRole("checkbox", {
    name: /Send this photo to Meta Muse/,
  });
  const ask = guided.getByRole("button", {
    name: "Suggest materials from this photo",
    exact: true,
  });
  await consent.check();
  await ask.click();
  await guided
    .getByRole("alert")
    .filter({ hasText: /missing required information/ })
    .waitFor();
  await guided.getByText(/input tokens: 2,200/i).waitFor();
  assert.equal(calls, 2);
  assert.equal(await consent.isChecked(), false);
  assert.doesNotMatch(await guided.innerText(), /PRIVATE_PROVIDER_CONTENT/);
  await guided.getByLabel("Photo to work on").selectOption("photo-a");
  assert.equal(await guided.getByText(/input tokens: 2,200/i).count(), 0);
  mode = "held";
  await consent.check();
  await ask.click();
  await guided.getByRole("button", { name: "Cancel", exact: true }).click();
  assert.equal(await guided.getByText(/input tokens: 2,200/i).count(), 0);
  release();
  await guided.getByText(/Cancelled\. FORMA stopped waiting/).waitFor();
  mode = "success";
  await consent.check();
  await ask.click();
  await guided.getByText(/input tokens: 2,200/i).waitFor();
  await guided.getByText(/Muse suggested 1 material/).waitFor();
  assert.equal(calls, 4);
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  console.log(
    "PASS guided intake: safe schema failure/usage, consent, context reset, cancel, successful usage",
  );
} finally {
  await browser.close();
}
