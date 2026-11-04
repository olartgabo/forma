// Intercepted UI acceptance only. No real provider, order or physical evidence.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const [modulePath, baseUrl] = process.argv.slice(2);
if (!modulePath || !baseUrl)
  throw new Error(
    "Usage: node sourcing.browser.mjs <Playwright module> <local web URL>",
  );
const origin = new URL(baseUrl);
if (!["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))
  throw new Error("Local web server required");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
const projects = [
  {
    id: "sourcing-a",
    revision_id: "revision-a",
    goal: "Sourcing project A",
    inventory_confirmed: false,
    active_version_id: null,
  },
  {
    id: "sourcing-b",
    revision_id: "revision-b",
    goal: "Sourcing project B",
    inventory_confirmed: false,
    active_version_id: null,
  },
];
try {
  for (const width of [1280, 390]) {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      serviceWorkers: "block",
    });
    await context.addInitScript(() => {
      window.__formaGeolocationCalls = 0;
      window.__formaDenyLocation = true;
      navigator.geolocation.getCurrentPosition = (success, failure) => {
        window.__formaGeolocationCalls++;
        if (window.__formaDenyLocation) failure({ code: 1 });
        else
          success({
            coords: {
              latitude: -16.500123,
              longitude: -68.150456,
              accuracy: 30,
            },
          });
      };
    });
    const page = await context.newPage();
    const errors = [];
    const posts = [];
    let statusReads = 0;
    let unresolved = false;
    let completed = null;
    page.on("pageerror", (e) => errors.push(e.message));
    await context.route("**/*", async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== origin.origin)
        throw new Error("Unexpected external request");
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname === "/api/provider/status")
        return route.fulfill({ json: { configured: false } });
      if (url.pathname === "/api/projects")
        return route.fulfill({ json: { projects, next_cursor: null } });
      const exactProject = projects.find(
        (p) => url.pathname === `/api/projects/${p.id}`,
      );
      if (exactProject)
        return route.fulfill({
          json: { ...exactProject, stocks: [], requirements: null },
        });
      if (url.pathname.endsWith("/media"))
        return route.fulfill({ json: { media: [] } });
      const p = projects.find((p) =>
        url.pathname.startsWith(`/api/projects/${p.id}/`),
      );
      if (url.pathname.endsWith("/sourcing/reverse")) {
        const { location } = req.postDataJSON();
        assert.equal(location.latitude, -16.5);
        assert.equal(location.longitude, -68.15);
        assert.equal(location.transfer_consented, true);
        return route.fulfill({
          json: {
            location: {
              ...location,
              city: "La Paz",
              country_code: "BO",
              label: "La Paz, Bolivia",
            },
            suggested_currency: "BOB",
            attribution: "OpenStreetMap test fixture",
          },
        });
      }
      if (url.pathname.endsWith("/sourcing/locations"))
        return route.fulfill({
          json: {
            choices: [
              {
                id: "relation/1",
                label: "La Paz, Bolivia",
                latitude: -16.5,
                longitude: -68.15,
                accuracy_m: null,
                location_basis: "city_center",
                country_code: "BO",
              },
            ],
            attribution: "OpenStreetMap test fixture",
          },
        });
      if (url.pathname.endsWith("/sourcing/needs"))
        return route.fulfill({
          json: {
            project_id: p.id,
            revision_id: p.revision_id,
            active_version_id: null,
            needs: [],
            guidance: ["Measure the sheet before deciding to buy more."],
            marketplace_status: "authorization_required",
            pending_run_id:
              p.id === "sourcing-a" && unresolved ? "research-run" : null,
          },
        });
      const result = {
        item: "one pair of scissors",
        area: "La Paz, Bolivia",
        currency: "BOB",
        id: "research-run",
        project_id: p?.id,
        revision_id: p?.revision_id,
        observed_at: "2026-11-04T12:00:00Z",
        status: "outcome_unknown",
        offers: [],
        usage: null,
        error: "provider_outcome_unknown",
        replayed: false,
      };
      if (url.pathname.endsWith("/sourcing/research")) {
        assert.equal(req.method(), "POST");
        posts.push(req.postDataJSON());
        if (posts.length > 1) {
          completed = {
            ...result,
            status: "succeeded",
            error: null,
            offers: [
              {
                title: "Observed scissors",
                url: "https://supplier.example/scissors",
                price: "25.00",
                currency: "BOB",
                price_status: "listed",
                availability: "Listed; not confirmed",
                location: "La Paz",
                notes: "Delivery unknown",
              },
            ],
          };
          return route.fulfill({
            json: { ...result, status: "running", error: null },
          });
        }
        unresolved = true;
        return route.fulfill({ json: result });
      }
      if (url.pathname.endsWith("/sourcing/research/research-run")) {
        assert.equal(req.method(), "GET");
        statusReads++;
        unresolved = false;
        return route.fulfill({
          json: completed ?? {
            ...result,
            status: "no_verified_results",
            error: null,
          },
        });
      }
      if (req.method() !== "GET")
        throw new Error(`Unexpected mutation ${req.method()} ${url.pathname}`);
      if (url.pathname.endsWith("/plans"))
        return route.fulfill({ json: { plans: [] } });
      if (url.pathname.endsWith("/construction/preview"))
        return route.fulfill({ status: 404, json: { code: "not_found" } });
      throw new Error(`Unexpected API ${url.pathname}`);
    });
    await page.goto(baseUrl);
    await page
      .getByLabel("Owner credential", { exact: true })
      .fill("synthetic-sourcing-owner");
    await page
      .getByRole("button", { name: "Open workbench", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Shopping list", exact: true })
      .click();
    await page.getByLabel("Shopping project").selectOption("sourcing-a");
    await page
      .getByText("Measure the sheet before deciding to buy more.")
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", {
          name: "Find nearby suppliers and prices",
          exact: true,
        })
        .isDisabled(),
      true,
    );
    assert.equal(await page.evaluate(() => window.__formaGeolocationCalls), 0);
    const locate = page.getByRole("button", {
      name: "Use my location",
      exact: true,
    });
    assert.equal(await locate.isDisabled(), true);
    await page.getByRole("checkbox", { name: /Allow map lookup/ }).check();
    await locate.click();
    await page.getByText(/Location permission was denied/).waitFor();
    assert.equal(
      await page.getByLabel("City and country", { exact: true }).isVisible(),
      true,
    );
    await page.evaluate(() => {
      window.__formaDenyLocation = false;
    });
    await locate.click();
    await page.getByText(/Confirmed: La Paz, Bolivia/).waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "Confirm search area", exact: true })
        .count(),
      0,
    );
    assert.equal(
      await page.getByLabel("Price currency", { exact: true }).inputValue(),
      "BOB",
    );
    assert.equal(await page.evaluate(() => window.__formaGeolocationCalls), 2);
    // Switch to the explicit manual fallback for the unknown/remount scenario.
    await page.getByRole("checkbox", { name: /Allow map lookup/ }).uncheck();
    await page.getByLabel("Item to research").fill("one pair of scissors");
    await page.getByLabel("Price currency", { exact: true }).fill("BOB");
    if (
      !(await page.getByLabel("City and country", { exact: true }).isVisible())
    )
      await page.getByText("Enter a city instead", { exact: true }).click();
    await page.getByLabel("City and country", { exact: true }).fill("La Paz");
    await page.getByRole("checkbox", { name: /Allow map lookup/ }).check();
    await page
      .getByRole("checkbox", { name: /Allow Meta price research/ })
      .check();
    await page
      .getByRole("button", { name: "Resolve city", exact: true })
      .click();
    await page
      .getByRole("radio", { name: "La Paz, Bolivia", exact: true })
      .check();
    await page
      .getByRole("button", { name: "Confirm search area", exact: true })
      .click();
    await page
      .getByRole("button", {
        name: "Find nearby suppliers and prices",
        exact: true,
      })
      .click();
    await page
      .getByText("The previous research outcome is unresolved.", {
        exact: false,
      })
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", {
          name: "Find nearby suppliers and prices",
          exact: true,
        })
        .isDisabled(),
      true,
    );
    assert.equal(posts.length, 1);
    assert.equal(posts[0].provider_transfer_consented, true);
    assert.equal(posts[0].location.confirmed, true);
    assert.equal(posts[0].supplier_url, undefined);
    assert.equal(posts[0].source, "suppliers");
    await page.getByLabel("Shopping project").selectOption("sourcing-b");
    await page.getByLabel("Item to research").waitFor();
    await page.getByLabel("Shopping project").selectOption("sourcing-a");
    await page
      .getByRole("button", { name: "Check research status", exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", {
          name: "Find nearby suppliers and prices",
          exact: true,
        })
        .isDisabled(),
      true,
      "pending survives remount",
    );
    await page
      .getByRole("button", { name: "Check research status", exact: true })
      .click();
    await page
      .getByRole("heading", {
        name: "No verified supplier results",
        exact: true,
      })
      .waitFor();
    assert.equal(statusReads, 1);
    assert.equal(posts.length, 1);
    await page.getByLabel("Item to research").fill("one pair of scissors");
    await page.getByLabel("Price currency", { exact: true }).fill("BOB");
    if (
      !(await page.getByLabel("City and country", { exact: true }).isVisible())
    )
      await page.getByText("Enter a city instead", { exact: true }).click();
    await page.getByLabel("City and country", { exact: true }).fill("La Paz");
    await page.getByRole("checkbox", { name: /Allow map lookup/ }).check();
    await page
      .getByRole("checkbox", { name: /Allow Meta price research/ })
      .check();
    await page
      .getByRole("button", { name: "Resolve city", exact: true })
      .click();
    await page
      .getByRole("radio", { name: "La Paz, Bolivia", exact: true })
      .check();
    await page
      .getByRole("button", { name: "Confirm search area", exact: true })
      .click();
    await page
      .getByRole("button", {
        name: "Find nearby suppliers and prices",
        exact: true,
      })
      .click();
    await page
      .getByRole("link", { name: "Observed scissors", exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("link", { name: "Observed scissors", exact: true })
        .getAttribute("href"),
      "https://supplier.example/scissors",
    );
    await page.getByText("BOB 25.00", { exact: true }).waitFor();
    assert.equal(posts.length, 2);
    assert.equal(
      statusReads,
      2,
      "Running response is polled with GET without a further POST",
    );
    assert.equal(
      await page
        .getByRole("link", { name: /Open Facebook Marketplace/ })
        .getAttribute("href"),
      "https://www.facebook.com/marketplace/",
    );
    await page.getByLabel("Shopping project").selectOption("sourcing-b");
    await page.getByLabel("Item to research").waitFor();
    assert.equal(await page.getByLabel("Item to research").inputValue(), "");
    assert.equal(
      await page
        .getByRole("heading", {
          name: "No verified supplier results",
          exact: true,
        })
        .count(),
      0,
    );
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      "fits viewport",
    );
    assert.deepEqual(errors, []);
    console.log(
      `PASS sourcing ${width}px: consent, pending/reconcile, external handoff, project isolation; intercepted provider`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
