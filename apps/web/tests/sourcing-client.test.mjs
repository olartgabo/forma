import assert from "node:assert/strict";
import { test } from "node:test";
import {
  loadSourcingNeeds,
  researchSuppliers,
  reconcileResearch,
  safeSupplierUrl,
  validateResearchRun,
  resolveSourcingLocation,
  discoverNearby,
  reverseSourcingLocation,
  pollResearch,
} from "../src/lib/sourcing-client.ts";

const body = {
  expected_revision_id: "revision",
  idempotency_key: "same-request-key",
  item: "scissors",
  area: "La Paz",
  currency: "BOB",
  provider_transfer_consented: true,
  source: "suppliers",
};
const run = () => ({
  item: body.item,
  area: body.area,
  currency: body.currency,
  id: "run",
  project_id: "project",
  revision_id: "revision",
  status: "succeeded",
  observed_at: "2026-11-04T12:00:00Z",
  error: null,
  replayed: false,
  usage: null,
  offers: [
    {
      title: "Supplier scissors",
      url: "https://supplier.example/scissors",
      price: "25.00",
      currency: "BOB",
      price_status: "listed",
      availability: "Listed, not confirmed",
      location: "La Paz",
      notes: "Delivery cost unknown",
    },
  ],
});

const mappedPlace = () => ({
  id: "node/123",
  name: "Synthetic mapped shop",
  latitude: 37.775,
  longitude: -122.419,
  distance_m: 123,
  distance_min_m: null,
  distance_max_m: null,
  address: "Synthetic address",
  website: null,
  osm_url: "https://www.openstreetmap.org/node/123",
  category: "hardware",
});

test("city resolution sends an explicit authenticated consented read request with no automatic selection", async (t) => {
  const calls = [];
  const choices = [1, 2].map((id) => ({
    id: String(id),
    label: `Synthetic city ${id}`,
    latitude: 37,
    longitude: -122,
    accuracy_m: null,
    location_basis: "city_center",
    country_code: "US",
  }));
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({ choices, attribution: "OpenStreetMap" }),
    };
  });
  const value = await resolveSourcingLocation(
    "secret",
    "project",
    "City, Country",
    true,
    signal(),
  );
  assert.deepEqual(value.choices, choices);
  assert.equal("confirmed" in value.choices[0], false);
  assert.equal(calls[0].url, "/api/projects/project/sourcing/locations");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    city: "City, Country",
    transfer_consented: true,
  });
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret");
  assert.equal(calls[0].options.credentials, "omit");
});

test("nearby mapped facts remain separate from prices and city-center offset remains unknown", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true,
    json: async () => ({
      places: [mappedPlace()],
      status: "found",
      attribution: "OpenStreetMap",
      message: "Stock unverified",
    }),
  }));
  const result = await discoverNearby(
    "secret",
    "project",
    {
      location: {
        latitude: 37,
        longitude: -122,
        accuracy_m: null,
        location_basis: "city_center",
        label: "City",
        confirmed: true,
        transfer_consented: true,
      },
      radius_m: 5000,
      category: "hardware",
    },
    signal(),
  );
  assert.equal(result.places[0].distance_min_m, null);
  assert.equal("price" in result.places[0], false);
  assert.equal("offers" in result, false);
});

test("malformed nearby evidence and unsafe map links fail closed", () => {
  for (const change of [
    { osm_url: "https://supplier.example/node/123" },
    { website: "https://localhost/secret" },
    { latitude: 100 },
    { distance_m: -1 },
    { distance_min_m: 140, distance_max_m: 200 },
  ])
    assert.throws(() =>
      validateResearchRun(
        { ...run(), nearby_places: [{ ...mappedPlace(), ...change }] },
        "project",
        "revision",
      ),
    );
  assert.equal(
    validateResearchRun(
      {
        ...run(),
        nearby_places: [mappedPlace()],
        discovery_message: "No matching published price",
      },
      "project",
      "revision",
    ).nearby_places.length,
    1,
  );
});

test("failed read-only geocoding cannot create an uncertain paid research reservation", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("transport");
  });
  await assert.rejects(
    resolveSourcingLocation(
      "secret",
      "project",
      "City, Country",
      true,
      signal(),
    ),
    (error) => error.uncertain === false,
  );
  assert.equal(calls, 1);
});
test("city resolution cannot dispatch without separate external map consent", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("must not dispatch");
  });
  await assert.rejects(
    resolveSourcingLocation(
      "secret",
      "project",
      "City, Country",
      false,
      signal(),
    ),
    (error) => error.code === "location_consent_required",
  );
  assert.equal(calls, 0);
});
const signal = () => new AbortController().signal;

test("explicit supplier-page inspection sends its URL without Meta consent or extra requests", async (t) => {
  const submitted = {
    ...body,
    source: "supplier_page",
    supplier_url: "https://www.tramontinastore.com.bo/shop/item",
    provider_transfer_consented: false,
  };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => run() };
  });
  const result = await researchSuppliers(
    "secret",
    "project",
    submitted,
    signal(),
  );
  assert.equal(result.status, "succeeded");
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(calls[0].options.body), submitted);
});
test("malformed successful POST and substituted request context remain uncertain", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true,
    json: async () => {
      throw new SyntaxError("broken response");
    },
  }));
  await assert.rejects(
    researchSuppliers("secret", "project", body, signal()),
    (e) => e.uncertain && e.code === "invalid_response",
  );
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true,
    json: async () => ({ ...run(), item: "other item" }),
  }));
  await assert.rejects(
    researchSuppliers("secret", "project", body, signal()),
    (e) => e.uncertain,
  );
});
test("unresolved earlier run blocks new request as uncertain rather than stale revision", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false,
    status: 409,
    json: async () => ({ code: "outcome_unknown" }),
  }));
  await assert.rejects(
    researchSuppliers("secret", "project", body, signal()),
    (e) => e.uncertain && e.code === "outcome_unknown",
  );
});
test("research sends only explicit request with secure same-origin fetch options", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => run() };
  });
  assert.equal(
    (await researchSuppliers("secret", "project", body, signal())).offers
      .length,
    1,
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/projects/project/sourcing/research");
  assert.deepEqual(JSON.parse(calls[0].options.body), body);
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret");
  assert.equal(calls[0].options.redirect, "error");
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.cache, "no-store");
});
test("cross-project, stale revision and unsafe source links fail closed", () => {
  for (const change of [
    { project_id: "other" },
    { revision_id: "old" },
    { offers: [{ ...run().offers[0], url: "javascript:alert(1)" }] },
    {
      offers: [
        { ...run().offers[0], url: "https://facebook.com/marketplace/item/1" },
      ],
    },
  ])
    assert.throws(() =>
      validateResearchRun({ ...run(), ...change }, "project", "revision"),
    );
});
test("unknown prices are never silently numeric zero and null remains unknown", () => {
  const unknown = {
    ...run().offers[0],
    price: null,
    price_status: "price_unknown",
  };
  assert.equal(
    validateResearchRun({ ...run(), offers: [unknown] }, "project", "revision")
      .offers[0].price,
    null,
  );
  assert.throws(() =>
    validateResearchRun(
      { ...run(), offers: [{ ...unknown, price: "0" }] },
      "project",
      "revision",
    ),
  );
  for (const price of [0, "-1", "NaN", "Infinity"])
    assert.throws(() =>
      validateResearchRun(
        { ...run(), offers: [{ ...unknown, price }] },
        "project",
        "revision",
      ),
    );
});
test("Marketplace and private credential URLs cannot appear as supplier results", () => {
  for (const url of [
    "http://supplier.example",
    "https://user:password@supplier.example",
    "https://127.0.0.1/api",
    "https://localhost/api",
    "https://x.local/api",
    "https://[::1]/",
    "https://m.facebook.com/item",
    "https://fb.me/x",
  ])
    assert.equal(safeSupplierUrl(url), false, url);
  assert.equal(safeSupplierUrl("https://supplier.example/item"), true);
});
test("lost POST outcome is uncertain with one request and no automatic retry", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("private transport details");
  });
  await assert.rejects(
    researchSuppliers("secret", "project", body, signal()),
    (e) => e.uncertain && !e.message.includes("private"),
  );
  assert.equal(calls, 1);
});
test("source unavailable is explicit and does not imply an unknown charge", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: false,
    status: 503,
    json: async () => ({ code: "source_unavailable" }),
  }));
  await assert.rejects(
    researchSuppliers("secret", "project", body, signal()),
    (e) => !e.uncertain && e.code === "source_unavailable",
  );
});
test("read-only reconciliation validates exact run identity", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ ...run(), id: "other" }) };
  });
  await assert.rejects(
    reconcileResearch("secret", "project", "revision", "run", signal()),
  );
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.body, undefined);
});
test("needs reject foreign project and keep guidance distinct from shopping requirements", async (t) => {
  const needs = {
    project_id: "project",
    revision_id: "revision",
    active_version_id: null,
    marketplace_status: "authorization_required",
    needs: [],
    guidance: ["Measure existing sheet first"],
  };
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true,
    json: async () => needs,
  }));
  assert.deepEqual(
    (await loadSourcingNeeds("secret", "project", signal())).needs,
    [],
  );
  await assert.rejects(loadSourcingNeeds("secret", "foreign", signal()));
});

const device = {
  latitude: -16.5,
  longitude: -68.15,
  accuracy_m: 30,
  location_basis: "device",
  label: "Approximate device area",
  confirmed: true,
  transfer_consented: true,
};
test("reverse requires map consent and preserves the confirmed rounded point and accuracy", async (t) => {
  const calls = [];
  const enriched = {
    ...device,
    label: "La Paz, Bolivia",
    city: "La Paz",
    country_code: "BO",
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        location: enriched,
        suggested_currency: "BOB",
        attribution: "OpenStreetMap",
      }),
    };
  });
  await assert.rejects(
    reverseSourcingLocation(
      "secret",
      "project",
      { ...device, transfer_consented: false },
      signal(),
    ),
  );
  assert.equal(calls.length, 0);
  const result = await reverseSourcingLocation(
    "secret",
    "project",
    device,
    signal(),
  );
  assert.deepEqual(result.location, enriched);
  assert.equal(result.suggested_currency, "BOB");
  assert.equal(calls[0].url, "/api/projects/project/sourcing/reverse");
  assert.deepEqual(JSON.parse(calls[0].options.body), { location: device });
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true,
    json: async () => ({
      location: { ...enriched, latitude: -16.51 },
      suggested_currency: "BOB",
      attribution: "OpenStreetMap",
    }),
  }));
  await assert.rejects(
    reverseSourcingLocation("secret", "project", device, signal()),
  );
});
test("automatic research polling reads existing status, stops at unknown and never regenerates", async (t) => {
  const calls = [];
  let status = "running";
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    status = calls.length === 2 ? "outcome_unknown" : "running";
    return { ok: true, json: async () => ({ ...run(), status }) };
  });
  const updates = [];
  const result = await pollResearch(
    "secret",
    "project",
    { ...run(), status: "running" },
    signal(),
    (value) => updates.push(value),
    async () => {},
  );
  assert.equal(result.status, "outcome_unknown");
  assert.equal(calls.length, 2);
  assert.equal(updates.length, 2);
  assert(
    calls.every(
      (call) =>
        call.options.method === "GET" &&
        call.options.body === undefined &&
        call.url.endsWith("/research/run"),
    ),
  );
});
test("automatic polling has a finite 24-read bound and transport failure is not retried", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return { ok: true, json: async () => ({ ...run(), status: "running" }) };
  });
  const pending = { ...run(), status: "running" };
  assert.equal(
    (
      await pollResearch(
        "secret",
        "project",
        pending,
        signal(),
        () => {},
        async () => {},
      )
    ).status,
    "running",
  );
  assert.equal(calls, 24);
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("transport");
  });
  await assert.rejects(
    pollResearch(
      "secret",
      "project",
      pending,
      signal(),
      () => {},
      async () => {},
    ),
  );
  assert.equal(calls, 25);
});
