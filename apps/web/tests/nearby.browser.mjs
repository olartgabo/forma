// Live app acceptance: no API interception or invented shop/price evidence.
// Uses the real map/Meta/retail API. Optional browser GPS simulation is software input, not physical GPS evidence.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const [modulePath, baseUrl, city, currency, item, outputDirectory] =
  process.argv.slice(2);
const owner = process.env.FORMA_E2E_OWNER;
const project = process.env.FORMA_E2E_PROJECT_ID;
if (
  !modulePath ||
  !baseUrl ||
  !city ||
  !currency ||
  !item ||
  !owner ||
  !project
)
  throw new Error(
    "Usage: FORMA_E2E_OWNER and FORMA_E2E_PROJECT_ID required; node nearby.browser.mjs <Playwright module> <local URL> <city,country> <ISO currency> <item> [screenshots]",
  );
const origin = new URL(baseUrl);
const loopback =
  ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname) &&
  ["http:", "https:"].includes(origin.protocol);
if (
  (!loopback && origin.origin !== "https://52-0-105-215.sslip.io") ||
  origin.username ||
  origin.password ||
  origin.search ||
  origin.hash ||
  !["", "/"].includes(origin.pathname)
)
  throw new Error(
    "Only a loopback app or the authorized HTTPS FORMA deployment is allowed",
  );
const gpsInput = process.env.FORMA_E2E_GPS;
const gps = gpsInput
  ? gpsInput.split(",").map((value) => Number(value.trim()))
  : null;
if (
  gps &&
  (gps.length !== 2 ||
    gpsInput.split(",").some((value) => !value.trim()) ||
    !gps.every(Number.isFinite) ||
    Math.abs(gps[0]) > 90 ||
    Math.abs(gps[1]) > 180)
)
  throw new Error(
    "FORMA_E2E_GPS must contain finite latitude,longitude in range",
  );
const rounded = (value) => Math.round(value * 1000) / 1000;
const resultPath =
  process.env.FORMA_E2E_RESULT_PATH ||
  path.resolve(outputDirectory || "output", "nearby-live-result.json");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
try {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    serviceWorkers: "block",
    ...(gps
      ? {
          geolocation: { latitude: gps[0], longitude: gps[1], accuracy: 30 },
          permissions: ["geolocation"],
        }
      : {}),
  });
  // Count native browser location calls; GPS mode explicitly simulates only the device input.
  await context.addInitScript(() => {
    window.__formaGeolocationCalls = 0;
    const geo = navigator.geolocation;
    if (geo) {
      const original = geo.getCurrentPosition.bind(geo);
      geo.getCurrentPosition = (...args) => {
        window.__formaGeolocationCalls++;
        return original(...args);
      };
    }
  });
  const page = await context.newPage();
  const before = await (
    await context.request.get(`${baseUrl}/api/projects/${project}`, {
      headers: { Authorization: `Bearer ${owner}` },
      maxRedirects: 0,
    })
  ).json();
  const errors = [];
  const submitted = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.origin === origin.origin &&
      url.pathname.endsWith("/sourcing/research") &&
      request.method() === "POST"
    )
      submitted.push(request.postDataJSON());
  });
  await page.goto(baseUrl);
  assert.equal(
    new URL(page.url()).origin,
    origin.origin,
    "Do not enter the credential after a cross-origin redirect",
  );
  await page.getByLabel("Owner credential", { exact: true }).fill(owner);
  await page
    .getByRole("button", { name: "Open workbench", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Shopping list", exact: true })
    .click();
  await page.getByLabel("Shopping project").selectOption(project);
  await page.getByLabel("Item to research").fill(item);
  assert.equal(
    await page.getByLabel("Price currency", { exact: true }).inputValue(),
    "",
  );
  if (!gps)
    await page.getByLabel("Price currency", { exact: true }).fill(currency);
  if (process.env.FORMA_E2E_CATEGORY)
    await page
      .getByLabel("Shop category")
      .selectOption(process.env.FORMA_E2E_CATEGORY);
  const search = page.getByRole("button", {
    name: "Find nearby suppliers and prices",
    exact: true,
  });
  let reverseEvidence = null;
  if (gps) {
    assert.equal(await page.evaluate(() => window.__formaGeolocationCalls), 0);
    const locate = page.getByRole("button", {
      name: "Use my location",
      exact: true,
    });
    assert.equal(await locate.isDisabled(), true);
    await page.getByRole("checkbox", { name: /Allow map lookup/ }).check();
    const reverseResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/sourcing/reverse"),
      { timeout: 65000 },
    );
    await locate.click();
    const resolved = await reverseResponse;
    assert.equal(resolved.status(), 200);
    reverseEvidence = await resolved.json();
    const sentPoint = resolved.request().postDataJSON().location;
    assert.equal(sentPoint.latitude, rounded(gps[0]));
    assert.equal(sentPoint.longitude, rounded(gps[1]));
    assert.equal(reverseEvidence.location.latitude, rounded(gps[0]));
    assert.equal(reverseEvidence.location.longitude, rounded(gps[1]));
    assert.equal(reverseEvidence.location.location_basis, "device");
    assert(reverseEvidence.location.accuracy_m > 0);
    assert(
      reverseEvidence.location.city?.trim(),
      "Real reverse lookup must enrich the device point with a city",
    );
    await page
      .getByText(`Confirmed: ${reverseEvidence.location.label}.`, {
        exact: false,
      })
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "Confirm search area", exact: true })
        .count(),
      0,
    );
    assert.equal(
      await page.getByRole("group", { name: "Choose a city result" }).count(),
      0,
    );
    const currencyInput = page.getByLabel("Price currency", { exact: true });
    assert(
      reverseEvidence.suggested_currency,
      "Reverse lookup must suggest a currency",
    );
    assert.equal(
      await currencyInput.inputValue(),
      reverseEvidence.suggested_currency,
    );
    assert.equal(await currencyInput.isEditable(), true);
    await currencyInput.fill(currency);
    assert.equal(await currencyInput.inputValue(), currency);
    assert.equal(await page.evaluate(() => window.__formaGeolocationCalls), 1);
    assert.equal(
      await search.isDisabled(),
      true,
      "Map consent does not imply Meta consent",
    );
  } else {
    await page.getByText("Enter a city instead", { exact: true }).click();
    await page.getByLabel("City and country", { exact: true }).fill(city);
    assert.equal(
      await page
        .getByRole("button", { name: "Resolve city", exact: true })
        .isDisabled(),
      true,
    );
    assert.equal(await page.evaluate(() => window.__formaGeolocationCalls), 0);
    await page.getByRole("checkbox", { name: /Allow map lookup/ }).check();
    const resolution = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith("/sourcing/locations"),
    );
    await page
      .getByRole("button", { name: "Resolve city", exact: true })
      .click();
    const resolved = await resolution;
    assert.equal(resolved.status(), 200);
    const resolvedBody = await resolved.json();
    assert.ok(
      resolvedBody.choices.length > 0,
      "Real geocoder must return a city choice",
    );
    const radios = page
      .getByRole("group", { name: "Choose a city result" })
      .getByRole("radio");
    await radios.first().waitFor();
    assert.equal(await radios.count(), resolvedBody.choices.length);
    for (let index = 0; index < (await radios.count()); index++)
      assert.equal(
        await radios.nth(index).isChecked(),
        false,
        "Ambiguous cities must never be selected automatically",
      );
    assert.equal(await search.isDisabled(), true);
    const chosen = process.env.FORMA_E2E_CITY_LABEL
      ? resolvedBody.choices.findIndex(
          (choice) => choice.label === process.env.FORMA_E2E_CITY_LABEL,
        )
      : 0;
    assert.ok(
      chosen >= 0,
      "Explicit operator city selection must match a returned choice",
    );
    await radios.nth(chosen).check();
    assert.equal(await search.isDisabled(), true);
    await page
      .getByRole("button", { name: "Confirm search area", exact: true })
      .click();
  }
  await page
    .getByRole("checkbox", { name: /Allow Meta price research/ })
    .check();
  assert.equal(await search.isDisabled(), false);
  const researchDeadline = Date.now() + 180000;
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/sourcing/research"),
    { timeout: 60000 },
  );
  await search.click();
  const response = await responsePromise;
  assert.equal(response.status(), 200);
  let result = await response.json();
  const observations = [];
  async function saveEvidence(observationError = null) {
    await mkdir(path.dirname(resultPath), { recursive: true });
    await writeFile(
      resultPath,
      JSON.stringify(
        {
          request: submitted[0],
          result,
          observations,
          reverse: reverseEvidence,
          simulatedBrowserGps: !!gps,
          physicalGpsClaim: false,
          observationError,
        },
        null,
        2,
      ),
    );
  }
  try {
    for (let count = 0; result.status === "running" && count < 24; count++) {
      const remaining = researchDeadline - Date.now();
      assert(
        remaining > 0,
        "Research observation reached its three-minute deadline",
      );
      const update = await page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname.endsWith(
            `/sourcing/research/${encodeURIComponent(result.id)}`,
          ),
        { timeout: Math.min(65000, remaining) },
      );
      assert.equal(update.request().method(), "GET");
      assert.equal(update.status(), 200);
      result = await update.json();
      observations.push({
        status: result.status,
        observed_at: result.observed_at,
      });
    }
  } catch (error) {
    await saveEvidence(
      error instanceof Error ? error.message : "Observation failed",
    );
    throw error;
  }
  await saveEvidence();
  assert(
    !["running", "outcome_unknown"].includes(result.status),
    "Pending or unknown outcome is not a completed live acceptance; evidence saved",
  );
  assert.equal(submitted.length, 1, "No duplicate automatic research requests");
  assert.equal(submitted[0].source, "suppliers");
  assert.equal(submitted[0].provider_transfer_consented, true);
  assert.equal(submitted[0].supplier_url, undefined);
  assert.equal(submitted[0].location.confirmed, true);
  assert.equal(submitted[0].location.transfer_consented, true);
  if (gps) {
    assert.equal(submitted[0].location.location_basis, "device");
    assert.equal(submitted[0].location.latitude, rounded(gps[0]));
    assert.equal(submitted[0].location.longitude, rounded(gps[1]));
    assert(submitted[0].location.accuracy_m > 0);
    assert(submitted[0].location.city?.trim());
  } else {
    assert.equal(submitted[0].location.location_basis, "city_center");
    assert.equal(submitted[0].location.accuracy_m, null);
  }
  assert.equal(submitted[0].radius_m, 5000);
  const requirePrice = process.env.FORMA_E2E_PRICE_REQUIRED !== "0";
  assert.ok(
    result.nearby_places?.length > 0,
    "Real nearby mapped suppliers required",
  );
  if (requirePrice) {
    assert.ok(
      result.offers?.some((offer) => offer.price !== null),
      "Real published price required; empty results are not an end-to-end price pass",
    );
  }
  if (result.nearby_places?.length)
    await page
      .getByRole("region", { name: "Nearby mapped suppliers" })
      .waitFor();
  await page.getByText("Online published prices", { exact: true }).waitFor();
  if (result.nearby_places?.length)
    await page
      .getByText(/Branch stock and item price are unverified/)
      .first()
      .waitFor();
  assert.deepEqual(
    await (
      await context.request.get(`${baseUrl}/api/projects/${project}`, {
        headers: { Authorization: `Bearer ${owner}` },
        maxRedirects: 0,
      })
    ).json(),
    before,
    "Read-only research must preserve the actual saved project",
  );
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      ),
      false,
      `No horizontal overflow at ${width}px`,
    );
    if (outputDirectory) {
      await mkdir(outputDirectory, { recursive: true });
      await page.screenshot({
        path: path.resolve(outputDirectory, `nearby-live-${width}.png`),
        fullPage: true,
      });
    }
  }
  assert.equal(
    await page.evaluate(() => window.__formaGeolocationCalls),
    gps ? 1 : 0,
  );
  assert.equal(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage }).includes('"latitude"'),
    ),
    false,
  );
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify({
      cityRequested: city,
      cityConfirmed: submitted[0].location.label,
      status: result.status,
      priceAcceptancePassed: !!result.offers?.some(
        (offer) => offer.price !== null,
      ),
      projectUnchanged: true,
      mappedPlaces: result.nearby_places.length,
      publishedPrices: result.offers
        .filter((offer) => offer.price !== null)
        .map((offer) => ({
          title: offer.title,
          price: offer.price,
          currency: offer.currency,
          url: offer.url,
        })),
      widths: [390, 1280],
      geolocationRequests: gps ? 1 : 0,
      simulatedBrowserGps: !!gps,
      physicalGpsClaim: false,
      resultEvidence: resultPath,
      apiInterception: false,
    }),
  );
  await context.close();
} finally {
  await browser.close();
}
