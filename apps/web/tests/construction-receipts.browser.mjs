// Fresh browser with server-owned receipts; all API requests intercepted.
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
    const original = Object.freeze({
      idempotency_key: "original-server-key",
      digest: "b".repeat(64),
      state: "unknown",
      error_code: "timeout",
    });
    let state = "unknown",
      gets = 0,
      writes = 0;
    let releaseInitial;
    const initial = new Promise((resolve) => {
      releaseInitial = resolve;
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      const uuid = crypto.randomUUID.bind(crypto);
      window.uuidCalls = 0;
      crypto.randomUUID = () => {
        window.uuidCalls++;
        return uuid();
      };
    });
    const base = `/api/projects/${fixture.project.id}`;
    await context.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin.origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (route.request().method() !== "GET") {
        if (url.pathname.startsWith(`${base}/construction/`)) writes++;
        return route.fulfill({ status: 503, json: { code: "unavailable" } });
      }
      if (url.pathname === `${base}/construction/receipts`) {
        gets++;
        assert.equal(
          route.request().headers().authorization,
          "Bearer offline-owner",
        );
        await initial;
        if (state === "unavailable")
          return route.fulfill({
            status: 503,
            json: { message: "SECRET provider body" },
          });
        return route.fulfill({
          json: {
            receipts: [
              {
                ...original,
                state,
                error_code: state === "unknown" ? "timeout" : null,
              },
            ],
          },
        });
      }
      const responses = {
        "/api/provider/status": { configured: true, model: "offline" },
        "/api/projects": { projects: [], next_cursor: null },
        [base]: fixture.project,
        [`${base}/media`]: { media: [] },
        [`${base}/plans`]: { plans: [] },
      };
      return route.fulfill(
        responses[url.pathname]
          ? { json: responses[url.pathname] }
          : { status: 404, json: { code: "not_found" } },
      );
    });
    await page.goto(`${origin.origin}/?project=${fixture.project.id}`);
    await page.evaluate(
      (t) => localStorage.setItem("forma.visitor-token", t),
      "offline-owner",
    );
    await page.getByRole("button", { name: "Open workbench" }).click();
    await page.getByRole("button", { name: "Detailed entry" }).click();
    const panel = page.getByRole("region", {
      name: "Invent with my materials",
    });
    const ask = panel.getByRole("button", {
      name: "Ask MetaMuse for shapes and steps",
    });
    const status = panel.getByRole("region", {
      name: "Saved construction request status",
    });
    await status.getByText(/Checking saved request status/).waitFor();
    assert.equal(await ask.isDisabled(), true, "initial read gates generation");
    releaseInitial();
    await status.getByText(/Stored request state: unknown/).waitFor();
    assert.match(await status.innerText(), /Stored cause: timeout/);
    assert.match(
      await status.innerText(),
      /cannot recover a missing provider result/,
    );
    await status.getByText("Original request identity").click();
    assert.ok((await status.innerText()).includes(original.digest));
    assert.equal(await ask.isDisabled(), true);
    assert.equal(
      await page.evaluate(
        () =>
          Object.keys(localStorage).filter((key) =>
            key.startsWith("forma-construction-pending-v1:"),
          ).length,
      ),
      0,
    );
    const uuidCalls = await page.evaluate(() => window.uuidCalls);
    const check = status.getByRole("button", {
      name: "Check request status",
      exact: true,
    });
    await check.click();
    await check.waitFor({ state: "visible" });
    await page.waitForFunction(
      () =>
        ![...document.querySelectorAll("button")].find(
          (button) => button.textContent === "Check request status",
        )?.disabled,
    );
    state = "unavailable";
    await check.click();
    await status.getByRole("alert").waitFor();
    assert.equal(await ask.isDisabled(), true);
    assert.ok(!(await status.innerText()).includes("SECRET"));
    state = "pending";
    await check.click();
    await status.getByText(/Stored request state: pending/).waitFor();
    assert.equal(await ask.isDisabled(), true);
    state = "completed";
    await check.click();
    await page.waitForFunction(
      () =>
        ![...document.querySelectorAll("button")].find(
          (button) => button.textContent === "Check request status",
        )?.disabled,
    );
    await panel.getByLabel(/Send the saved goal/).check();
    assert.equal(
      await ask.isEnabled(),
      true,
      "confirmed completed status permits a separately consented request",
    );
    assert.equal(
      await page.evaluate(() => window.uuidCalls),
      uuidCalls,
      "status checks create no request identity",
    );
    assert.equal(writes, 0, "status checks perform no POST or other writes");
    assert.equal(original.state, "unknown");
    assert.deepEqual(errors, []);
    await context.close();
    console.log(
      `PASS ${width}px fresh-browser server receipt gating, safe cause/identity, initial/failure closed, GET-only refresh and zero UUID/POST`,
    );
  }
} finally {
  await browser.close();
}
