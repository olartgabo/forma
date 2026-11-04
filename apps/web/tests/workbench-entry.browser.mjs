// Runs against local Next. The API responses below are synthetic.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl] = process.argv.slice(2);
if (!modulePath || !baseUrl)
  throw new Error(
    "Usage: node workbench-entry.browser.mjs <playwright module path> <local web URL>",
  );
const origin = new URL(baseUrl);
assert(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});

try {
  const page = await browser.newPage({
    viewport: { width: 375, height: 812 },
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  const errors = [];
  const unexpected = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let entryReads = 0;
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === origin.origin && !url.pathname.startsWith("/api/"))
      return route.continue();
    if (url.origin === origin.origin && request.method() === "GET") {
      if (url.pathname === "/api/provider/status")
        return route.fulfill({ json: { configured: false } });
      if (url.pathname === "/api/projects") {
        if (url.searchParams.get("limit") === "1") entryReads++;
        if (request.headers().authorization === "Bearer synthetic-owner")
          return route.fulfill({ json: { projects: [], next_cursor: null } });
        if (request.headers().authorization === "Bearer synthetic-unavailable")
          return route.fulfill({ status: 503, json: {} });
        return route.fulfill({ status: 401, json: {} });
      }
    }
    unexpected.push(`${request.method()} ${url.pathname}`);
    return route.abort();
  });

  await page.goto(baseUrl);
  const spanish = page.getByRole("button", { name: "Español" });
  await spanish.click();
  await page
    .getByRole("heading", { name: "Empieza con lo que tienes." })
    .waitFor();
  await page.reload();
  await page.locator('html[lang="es"]').waitFor({ state: "attached" });
  assert.equal(await spanish.getAttribute("aria-pressed"), "true");

  const front = page.getByRole("button", { name: "Frente" });
  const back = page.getByRole("button", { name: "Reverso" });
  await front.click();
  const model = page.locator("[data-back]");
  const transform = () =>
    model.evaluate((node) => getComputedStyle(node).transform);
  const frontView = await transform();
  assert.match(frontView, /^matrix3d/);
  await back.click();
  assert.notEqual(await transform(), frontView);
  assert.equal(await back.getAttribute("aria-pressed"), "true");
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );

  const credential = page.getByLabel("Credencial de propietario");
  const open = page.getByRole("button", { name: "Abrir espacio de trabajo" });
  await credential.fill("wrong-test-credential");
  await open.click();
  await page.getByText(/Se rechazó la credencial/).waitFor();
  assert.equal(await page.getByText("Espacio de trabajo privado").count(), 0);
  await credential.fill("synthetic-unavailable");
  await open.click();
  await page.getByText(/No pudimos comprobar el acceso/).waitFor();
  assert.equal(await credential.inputValue(), "synthetic-unavailable");
  await credential.fill("  synthetic-owner  ");
  await credential.press("Enter");
  await page
    .getByRole("heading", { name: "¿Qué necesitas en tu escritorio?" })
    .waitFor();
  await page.getByText("Todavía no hay proyectos guardados.").waitFor();
  assert.equal(entryReads, 3);
  assert.deepEqual(await page.evaluate(() => ({ ...localStorage })), {
    "forma-language": "es",
  });
  await page.getByRole("button", { name: "English" }).click();
  await page
    .getByRole("heading", { name: "What would make your desk work better?" })
    .waitFor();
  await page.getByRole("button", { name: "Disconnect" }).click();
  assert.equal(await page.getByLabel("Owner credential").inputValue(), "");
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  console.log(
    "PASS: entry language, persisted selection, 3D views, credential rejection and retry, and disconnect",
  );
} finally {
  await browser.close();
}
