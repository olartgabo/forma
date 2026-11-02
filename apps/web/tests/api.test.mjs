import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ApiError,
  activatePlan,
  approveRepair,
  createProject,
  deletePhoto,
  fetchPhoto,
  generateDesign,
  listPhotos,
  listPlans,
  listSavedProjects,
  loadDesignReadiness,
  loadPlan,
  loadProgress,
  loadProject,
  loadProof,
  requestDiagnosis,
  requestIntakeObservation,
  saveInventory,
  recordProgress,
  simulateRepairs,
  uploadPhoto,
} from "../src/lib/api.ts";
import {
  editConstraint,
  emptyRequirements,
  requirementsError,
} from "../src/lib/build-requirements.ts";
import { proofText, proofUnknowns } from "../src/lib/proof-report.ts";
import { createDiagnosisPlanLoader } from "../src/lib/diagnosis-plan-loader.ts";
import { formatProviderUsage } from "../src/lib/provider-usage.ts";
import {
  draftFromHandoff,
  handoffFromDiagnosis,
  isHandoffCurrent,
} from "../src/lib/repair-handoff.ts";

test("provider usage formats only provider-reported bounded counts", () => {
  assert.equal(
    formatProviderUsage({
      model_calls: 1,
      input_tokens: 1234,
      output_tokens: 56,
    }),
    "Provider-reported usage — model calls: 1; input tokens: 1,234; output tokens: 56.",
  );
  assert.equal(
    formatProviderUsage({
      model_calls: 2,
      input_tokens: 1234567,
      output_tokens: 89012,
    }),
    "Provider-reported usage — model calls: 2; input tokens: 1,234,567; output tokens: 89,012.",
  );
  for (const missing of [null, undefined, "PRIVATE", 42, true, []])
    assert.equal(
      formatProviderUsage(missing),
      "Provider-reported usage: not reported.",
    );
  assert.equal(
    formatProviderUsage({ model_calls: 1, input_tokens: null }),
    "Provider-reported usage — model calls: 1; input tokens: not reported; output tokens: not reported.",
  );
  assert.equal(
    formatProviderUsage({
      model_calls: 0,
      input_tokens: 0,
      output_tokens: 0,
    }),
    "Provider-reported usage — model calls: 0; input tokens: 0; output tokens: 0.",
  );
  for (const malformed of [
    { model_calls: "1", input_tokens: 10, output_tokens: 5 },
    { model_calls: 1.5, input_tokens: 10, output_tokens: 5 },
    { model_calls: -1, input_tokens: 10, output_tokens: 5 },
    { model_calls: 17, input_tokens: 10, output_tokens: 5 },
    { model_calls: 1, input_tokens: Number.NaN, output_tokens: 5 },
    {
      model_calls: 1,
      input_tokens: Number.POSITIVE_INFINITY,
      output_tokens: 5,
    },
    { model_calls: 1, input_tokens: 16_000_000_001, output_tokens: 5 },
    { model_calls: true, input_tokens: { value: 10 }, output_tokens: "5" },
  ]) {
    const formatted = formatProviderUsage(malformed);
    assert.match(formatted, /not reported/);
    assert.doesNotMatch(formatted, /PRIVATE|NaN|Infinity|\[object/);
  }
  assert.equal(
    formatProviderUsage({
      model_calls: 1,
      input_tokens: "PRIVATE_TOKEN_COUNT",
      output_tokens: 5,
    }),
    "Provider-reported usage — model calls: 1; input tokens: not reported; output tokens: 5.",
  );
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const flushAsync = () => new Promise((resolve) => setImmediate(resolve));

test("diagnosis plan loader retries only the current manual after failure", async () => {
  const key = {
    token: "token-a",
    projectId: "project-a",
    activeVersionId: "version-a",
  };
  const plan = { project_id: "project-a", version_id: "version-a" };
  const calls = [];
  const loader = createDiagnosisPlanLoader({
    load: async (loadKey) => {
      calls.push(loadKey);
      if (calls.length === 1) throw new Error("transient");
      return plan;
    },
    errorMessage: () => "The manual could not be loaded.",
  });
  loader.setKey(key);
  assert.equal(loader.getState().loading, true);
  assert.equal(loader.getState().plan, null);
  await flushAsync();
  assert.equal(loader.getState().loading, false);
  assert.equal(loader.getState().plan, null);
  assert.equal(loader.getState().error, "The manual could not be loaded.");
  loader.retry();
  assert.equal(loader.getState().loading, true);
  assert.equal(loader.getState().error, "");
  await flushAsync();
  assert.deepEqual(loader.getState().plan, plan);
  assert.equal(loader.getState().error, "");
  assert.equal(loader.getState().loading, false);
  assert.deepEqual(calls, [key, key]);
  loader.dispose();
});

test("diagnosis plan loader ignores a retry result after session and version change", async () => {
  const keyA = {
    token: "token-a",
    projectId: "project-a",
    activeVersionId: "version-a",
  };
  const keyB = {
    token: "token-b",
    projectId: "project-a",
    activeVersionId: "version-b",
  };
  const planA = { project_id: "project-a", version_id: "version-a" };
  const planB = { project_id: "project-a", version_id: "version-b" };
  const pending = [];
  const signals = [];
  const loader = createDiagnosisPlanLoader({
    load: (loadKey, signal) => {
      signals.push(signal);
      const next = deferred();
      pending.push(next);
      return next.promise;
    },
    errorMessage: () => "The manual could not be loaded.",
  });
  loader.setKey(keyA);
  pending[0].reject(new Error("transient"));
  await flushAsync();
  assert.equal(loader.getState().error, "The manual could not be loaded.");
  loader.retry();
  loader.retry();
  assert.equal(pending.length, 2);
  loader.setKey(keyB);
  assert.deepEqual(loader.getState().key, keyB);
  assert.equal(loader.getState().plan, null);
  assert.equal(loader.getState().error, "");
  assert.equal(loader.getState().loading, true);
  assert.equal(signals[1].aborted, true);
  pending[1].resolve(planA);
  await flushAsync();
  assert.deepEqual(loader.getState().key, keyB);
  assert.equal(loader.getState().plan, null);
  assert.equal(loader.getState().loading, true);
  pending[2].resolve(planB);
  await flushAsync();
  assert.deepEqual(loader.getState().plan, planB);
  assert.equal(loader.getState().loading, false);
  loader.dispose();
  assert.equal(loader.getState().plan, null);
});

const token = "synthetic-owner-credential";
const savedProject = {
  id: "project-a",
  goal: "A phone stand",
  revision_id: "inventory-1",
  stocks: [],
};

test("proof requests stay owner scoped and exports preserve failed versus unattempted claims", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json({ project: savedProject, versions: [] });
  });
  await loadProof(token, "project-a");
  assert.equal(calls[0].path, "/api/projects/project-a/proof");
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.equal(calls[0].options.cache, "no-store");
  const snapshot = {
    project: savedProject,
    generated_at: "2026-11-01T00:00:00Z",
    photos_omitted: 2,
    photo_policy: "excluded",
    coverage: "initial_plan_reports",
    versions: [
      {
        inventory_revision_id: "inventory-1",
        candidate_id: "synthetic-candidate",
        plan: {
          version_id: "version-a",
          compiler_version: "synthetic-compiler",
          operations: [
            {
              id: "test-a",
              type: "functional_test",
              args: {
                procedure: "Observe the specified fixture",
                device_label: "SYNTHETIC phone",
                mass_g: 180,
                duration_seconds: 60,
                surface: "SYNTHETIC desk",
                pass_criteria: ["No slip"],
              },
            },
          ],
        },
        progress: {
          status: "not_started",
          completed_operation_ids: [],
          events: [],
          evidence: [],
          material_transactions: [],
          expected_remaining_stock: [],
        },
      },
    ],
  };
  const initial = proofText(snapshot);
  assert.match(initial, /Result: not attempted/);
  assert.match(initial, /Private photos excluded: 2/);
  assert.match(initial, /evidence invalidation are not integrated/);
  assert.doesNotMatch(initial, /User-reported result: passed/);
  snapshot.versions[0].progress.status = "needs_review";
  snapshot.versions[0].progress.events.push({
    id: "synthetic-test-failure",
    kind: "test",
    operation_id: "test-a",
    test_result: "failed",
    verification_state: "failed",
    recorded_at: "2026-11-01T00:00:01Z",
    observation: "SYNTHETIC failure <script>literal text</script>",
  });
  const failed = proofText(snapshot);
  assert.match(failed, /User-reported result: failed/);
  assert.match(failed, /Device: SYNTHETIC phone/);
  assert.match(failed, /Mass: 180 g/);
  assert.match(failed, /literal text/);
  assert.doesNotMatch(failed, /Result: not attempted/);
});

test("proof unknowns report missing and unconfirmed inputs without inventing zeros", () => {
  const unknown = {
    value: null,
    unit: "mm",
    source: "unknown",
    confirmed: false,
  };
  const snapshot = {
    project: {
      ...savedProject,
      requirements: emptyRequirements(),
      stocks: [
        {
          id: "synthetic-sheet",
          kind: "sheet",
          condition: "uncertain",
          usable_regions: [],
          width_mm: unknown,
          height_mm: {
            value: 100,
            unit: "mm",
            source: "user_ruler",
            confirmed: false,
          },
          thickness_mm: unknown,
        },
      ],
    },
  };
  const unknowns = proofUnknowns(snapshot);
  assert.ok(unknowns.includes("synthetic-sheet: width mm unknown"));
  assert.ok(unknowns.includes("synthetic-sheet: height mm unconfirmed"));
  assert.ok(
    unknowns.includes("synthetic-sheet: usable starting regions not recorded"),
  );
  assert.ok(unknowns.includes("device mass g: unknown"));
  snapshot.project.stocks = [
    {
      id: "synthetic-tape",
      kind: "tape",
      condition: "usable",
      width_mm: unknown,
      remaining_length_mm: {
        value: 300,
        unit: "mm",
        source: "user_ruler",
        confirmed: true,
      },
    },
  ];
  assert.ok(
    proofUnknowns(snapshot).includes("synthetic-tape: width mm unknown"),
  );
  assert.doesNotMatch(unknowns.join("\n"), /0 mm/);
});

test("physical reports bind the active version and history cursor without accepting raw events", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json({ progress: {} });
  });
  const report = {
    expected_version_id: "version-a",
    expected_last_event_id: null,
    idempotency_key: "report-key",
    operation_id: "stand-cut-panels",
    result: "completed",
    observation: "SYNTHETIC browser report",
    user_confirmed: true,
    checks_confirmed: true,
    photo_ids: [],
  };
  await loadProgress(token, "project-a", "version-a");
  await recordProgress(token, "project-a", report);
  assert.equal(
    calls[0].path,
    "/api/projects/project-a/versions/version-a/progress",
  );
  assert.equal(calls[1].path, "/api/projects/project-a/events");
  assert.equal(calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[1].options.body), report);
  assert.equal(
    Object.hasOwn(JSON.parse(calls[1].options.body), "event"),
    false,
  );
  assert.equal(
    calls[1].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.equal(calls[1].options.cache, "no-store");
});

test("repair review sends typed candidates and approves only a preview reference", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json({ previews: [] });
  });
  const simulation = {
    expected_version_id: "version-a",
    expected_last_event_id: "event-a",
    idempotency_key: "simulate-key",
    candidates: [
      {
        id: "repair-a",
        base_version_id: "version-a",
        kind: "replace_part",
        target_id: "stand-brace",
        replacement_stock_id: "spare",
        replacement_profile_id: null,
        width_mm: null,
        height_mm: null,
        angle_deg: null,
        rationale: "SYNTHETIC torn brace",
      },
    ],
    connector_measurements: [{ stock_id: "tape", remaining_length_mm: 260 }],
    remaining_confirmed: true,
  };
  const approval = {
    expected_version_id: "version-a",
    expected_last_event_id: "event-a",
    preview_id: "preview-a",
    idempotency_key: "commit-key",
    user_approved: true,
  };
  await simulateRepairs(token, "project-a", simulation);
  await approveRepair(token, "project-a", approval);
  assert.equal(calls[0].path, "/api/projects/project-a/adapt/simulate");
  assert.deepEqual(JSON.parse(calls[0].options.body), simulation);
  assert.equal(calls[1].path, "/api/projects/project-a/adapt/commit");
  // Approval names a server-stored preview; the browser never sends a plan.
  assert.deepEqual(JSON.parse(calls[1].options.body), approval);
  for (const call of calls) {
    assert.equal(call.options.method, "POST");
    assert.equal(call.options.headers.get("Authorization"), `Bearer ${token}`);
    assert.equal(call.options.cache, "no-store");
  }
});

test("plan reads stay scoped and approval sends only a version reference", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json({ project: savedProject });
  });
  await listPlans(token, "project-a");
  await loadPlan(token, "project-a", "version-a");
  const approval = {
    expected_revision_id: "inventory-1",
    idempotency_key: "approve-key",
    user_approved: true,
  };
  await activatePlan(token, "project-a", "version-a", approval);
  assert.deepEqual(
    calls.map(({ path }) => path),
    [
      "/api/projects/project-a/plans",
      "/api/projects/project-a/versions/version-a",
      "/api/projects/project-a/plans/version-a/activate",
    ],
  );
  assert.equal(calls[2].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[2].options.body), approval);
  for (const { options } of calls) {
    assert.equal(options.headers.get("Authorization"), `Bearer ${token}`);
    assert.equal(options.cache, "no-store");
    assert.equal(options.redirect, "error");
  }
});

test("requirements retain unknowns and edited measurements require confirmation", () => {
  const requirements = emptyRequirements();
  assert.equal(requirementsError(requirements), null);
  for (const field of [
    "device_mass_g",
    "support_angle_deg",
    "max_footprint_width_mm",
    "max_footprint_height_mm",
  ])
    assert.equal(requirements.constraints[field].value, null);
  const confirmed = {
    ...requirements.constraints,
    device_mass_g: {
      value: 190,
      unit: "g",
      source: "known_reference",
      confirmed: true,
    },
  };
  const changed = editConstraint(confirmed, "device_mass_g", "200");
  assert.equal(changed.device_mass_g.confirmed, false);
  assert.equal(changed.device_mass_g.source, "user_ruler");
  assert.match(
    requirementsError({ ...requirements, constraints: changed }),
    /Confirm device mass/,
  );
  assert.equal(confirmed.device_mass_g.value, 190);
  assert.deepEqual(editConstraint(changed, "device_mass_g", "").device_mass_g, {
    value: null,
    unit: "g",
    source: "unknown",
    confirmed: false,
  });
  assert.match(
    requirementsError({ ...requirements, tools: ["Ruler", "ruler"] }),
    /once/,
  );
  assert.match(
    requirementsError({
      ...requirements,
      constraints: {
        ...requirements.constraints,
        support_angle_deg: {
          value: 90,
          unit: "deg",
          source: "user_ruler",
          confirmed: true,
        },
      },
    }),
    /between 0 and 90/,
  );
});

test("inventory requests carry requirements and distinguish omission from clearing", async (t) => {
  const bodies = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    bodies.push(JSON.parse(options.body));
    return Response.json({ project: savedProject });
  });
  const requirements = {
    ...emptyRequirements(),
    tools: ["Ruler"],
    device_description: "Phone with case",
  };
  await saveInventory(
    token,
    "project-a",
    [],
    "inventory-1",
    "save-key",
    undefined,
    requirements,
  );
  await saveInventory(
    token,
    "project-a",
    [],
    "inventory-1",
    "clear-key",
    undefined,
    null,
  );
  await saveInventory(token, "project-a", [], "inventory-1", "legacy-key");
  assert.deepEqual(bodies[0].requirements, requirements);
  assert.equal(bodies[0].expected_revision_id, "inventory-1");
  assert.equal(bodies[0].idempotency_key, "save-key");
  assert.equal(bodies[1].requirements, null);
  assert.equal(Object.hasOwn(bodies[2], "requirements"), false);
});

test("project requests preserve caller scope, explicit confirmations and retry keys", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json({ project: savedProject });
  });
  await createProject(token, "Un soporte para mi teléfono", "create-key");
  await saveInventory(token, "project-a", [], "inventory-1", "save-key");
  await loadProject(token, "project-a");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    goal: "Un soporte para mi teléfono",
    idempotency_key: "create-key",
  });
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    stocks: [],
    expected_revision_id: "inventory-1",
    idempotency_key: "save-key",
    user_confirmed: true,
  });
  assert.equal(calls[0].path, "/api/projects");
  assert.equal(calls[1].path, "/api/projects/project-a/inventory");
  assert.equal(calls[2].path, "/api/projects/project-a");
  for (const { options } of calls) {
    assert.equal(options.headers.get("Authorization"), `Bearer ${token}`);
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    assert.equal(options.cache, "no-store");
  }
});

test("photo requests use private blob downloads and scoped retry headers", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return options.method === "GET" && path.endsWith("/media-a")
      ? new Response("pixels", { headers: { "Content-Type": "image/png" } })
      : Response.json({ media: [] });
  });
  const file = new File(["pixels"], "private.png", { type: "image/png" });
  await uploadPhoto(token, "project-a", file, "upload-key");
  await listPhotos(token, "project-a");
  const blob = await fetchPhoto(token, "project-a", "media-a");
  await deletePhoto(token, "project-a", "media-a", "delete-key");
  assert.equal(calls[0].options.body, file);
  assert.equal(calls[0].options.headers.get("Content-Type"), "image/png");
  assert.equal(calls[0].options.headers.get("Idempotency-Key"), "upload-key");
  assert.equal(calls[1].path, "/api/projects/project-a/media");
  assert.equal(blob.type, "image/png");
  assert.equal(await blob.text(), "pixels");
  assert.equal(calls[3].path, "/api/projects/project-a/media/media-a");
  assert.equal(calls[3].options.headers.get("Idempotency-Key"), "delete-key");
});

test("error messages expose known conflict codes without echoing server content", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "stale_version", message: "PRIVATE_SERVER_TEXT" },
      { status: 409 },
    ),
  );
  await assert.rejects(loadProject(token, "project-a"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.equal(error.code, "stale_version");
    assert.match(error.message, /Reload before saving/);
    assert.doesNotMatch(error.message, /PRIVATE_SERVER_TEXT/);
    return true;
  });
});

test("HTML and unknown server errors become safe local failures", async (t) => {
  const responses = [
    new Response("PRIVATE_PROXY_TEXT", { status: 502 }),
    Response.json(
      { code: "PRIVATE_CODE", message: "PRIVATE_TEXT" },
      { status: 500 },
    ),
  ];
  t.mock.method(globalThis, "fetch", async () => responses.shift());
  for (const status of [502, 500]) {
    await assert.rejects(loadProject(token, "project-a"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.equal(error.code, "request_failed");
      assert.doesNotMatch(error.message, /PRIVATE/);
      return true;
    });
  }
});

test("non-object success payload is reported as unreadable", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json(null));
  await assert.rejects(loadProject(token, "project-a"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "invalid_response");
    return true;
  });
});

test("malformed success JSON is a safe unreadable response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("PRIVATE_HTML"));
  await assert.rejects(loadProject(token, "project-a"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 200);
    assert.equal(error.code, "invalid_response");
    assert.doesNotMatch(error.message, /PRIVATE_HTML/);
    return true;
  });
});

test("caller cancellation aborts the in-flight request", async (t) => {
  let requestSignal;
  t.mock.method(globalThis, "fetch", (path, options) => {
    requestSignal = options.signal;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("PRIVATE_ABORT_DETAIL", "AbortError")),
        { once: true },
      );
    });
  });
  const controller = new AbortController();
  const pending = loadProject(token, "project-a", controller.signal);
  controller.abort();
  await assert.rejects(pending, (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "cancelled");
    assert.doesNotMatch(error.message, /PRIVATE_ABORT_DETAIL/);
    return true;
  });
  assert.equal(requestSignal.aborted, true);
});

const intakeResult = {
  project_id: "project-a",
  revision_id: "inventory-1",
  media_id: "media-a",
  observation: {
    labels: ["cardboard sheet"],
    measurement_source: "unknown",
    questions: ["How thick is it?"],
  },
  diagnostics: { status: "ok", model: "muse-spark-test", elapsed_ms: 12 },
};

test("intake request sends exactly the scoped body with caller auth", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(intakeResult);
  });
  const result = await requestIntakeObservation(
    token,
    "project-a",
    "media-a",
    "inventory-1",
  );
  assert.deepEqual(result, intakeResult);
  assert.equal(calls[0].path, "/api/projects/project-a/intake");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    media_id: "media-a",
    expected_revision_id: "inventory-1",
    provider_transfer_consented: true,
  });
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
  assert.equal(calls[0].options.cache, "no-store");
});

test("intake provider errors use safe local messages and preserve codes", async (t) => {
  const cases = [
    [503, "provider_not_configured", /not configured/],
    [502, "provider_authentication", /credential was rejected/],
    [502, "access_denied", /denied access/],
    [429, "rate_limit", /rate limit/],
    [504, "timeout", /timed out/],
    [502, "network_error", /could not be reached/],
    [502, "invalid_response", /unusable response/],
    [422, "consent_required", /Consent to send/],
    [409, "stale_version", /Reload the project/],
  ];
  for (const [status, code, pattern] of cases) {
    t.mock.method(globalThis, "fetch", async () =>
      Response.json(
        { code, message: "PRIVATE_PROVIDER_BODY sk-secret" },
        { status },
      ),
    );
    await assert.rejects(
      requestIntakeObservation(token, "project-a", "media-a", "inventory-1"),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.equal(error.code, code);
        assert.match(error.message, pattern);
        assert.doesNotMatch(error.message, /PRIVATE|sk-secret/);
        return true;
      },
    );
    t.mock.restoreAll();
  }
});

test("intake 413/415 guidance differs from unchanged upload guidance", async (t) => {
  for (const [status, intakePattern, uploadPattern] of [
    [413, /5,000,000 bytes/, /8 MiB/],
    [415, /JPEG or PNG/, /JPEG, PNG or WebP/],
  ]) {
    t.mock.method(globalThis, "fetch", async () =>
      Response.json(
        { code: "validation_error", message: "PRIVATE_TEXT" },
        { status },
      ),
    );
    await assert.rejects(
      requestIntakeObservation(token, "project-a", "media-a", "inventory-1"),
      (error) => {
        assert.match(error.message, intakePattern);
        assert.doesNotMatch(error.message, /PRIVATE_TEXT/);
        return true;
      },
    );
    const file = new File(["pixels"], "private.webp", { type: "image/webp" });
    await assert.rejects(
      uploadPhoto(token, "project-a", file, "upload-key"),
      (error) => {
        assert.match(error.message, uploadPattern);
        assert.doesNotMatch(error.message, /PRIVATE_TEXT/);
        return true;
      },
    );
    t.mock.restoreAll();
  }
});

test("intake cancellation aborts without leaking abort details", async (t) => {
  let requestSignal;
  t.mock.method(globalThis, "fetch", (path, options) => {
    requestSignal = options.signal;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("PRIVATE_ABORT_DETAIL", "AbortError")),
        { once: true },
      );
    });
  });
  const controller = new AbortController();
  const pending = requestIntakeObservation(
    token,
    "project-a",
    "media-a",
    "inventory-1",
    controller.signal,
  );
  controller.abort();
  await assert.rejects(pending, (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "cancelled");
    assert.doesNotMatch(error.message, /PRIVATE_ABORT_DETAIL/);
    return true;
  });
  assert.equal(requestSignal.aborted, true);
});

test("intake scoped mismatch and unreadable shapes are rejected safely", async (t) => {
  const payloads = [
    { ...intakeResult, project_id: "project-other" },
    { ...intakeResult, revision_id: "inventory-2" },
    { ...intakeResult, media_id: "media-other" },
    {
      ...intakeResult,
      observation: {
        labels: "PRIVATE",
        measurement_source: "unknown",
        questions: [],
      },
    },
    {
      ...intakeResult,
      observation: { labels: [], measurement_source: "photo", questions: [] },
    },
  ];
  for (const payload of payloads) {
    t.mock.method(globalThis, "fetch", async () => Response.json(payload));
    await assert.rejects(
      requestIntakeObservation(token, "project-a", "media-a", "inventory-1"),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "invalid_response");
        assert.doesNotMatch(error.message, /PRIVATE/);
        return true;
      },
    );
    t.mock.restoreAll();
  }
});

const designResult = {
  project_id: "project-a",
  inventory_revision_id: "inventory-1",
  status: "proposed",
  candidates: [
    {
      candidate_id: "candidate-a",
      status: "accepted",
      version: {
        project_id: "project-a",
        version_id: "version-a",
        inventory_revision_id: "inventory-1",
        candidate_id: "candidate-a",
        created_at: "2026-11-01T00:00:00Z",
      },
      blockers: [],
    },
  ],
  questions: [],
  blockers: [],
  diagnostics: {
    status: "ok",
    model: "muse-spark-test",
    elapsed_ms: 25,
    model_rounds: 2,
    tool_executions: 1,
  },
};

const designBody = {
  expected_revision_id: "inventory-1",
  user_notes: "Compact please",
  idempotency_key: "design-key-1",
  provider_context_consented: true,
};

test("design request sends exactly the scoped body with caller auth", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(designResult);
  });
  const result = await generateDesign(token, "project-a", designBody);
  assert.deepEqual(result, designResult);
  assert.equal(calls[0].path, "/api/projects/project-a/designs/generate");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), designBody);
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
  assert.equal(calls[0].options.cache, "no-store");
});

test("design provider errors use safe local messages and preserve codes", async (t) => {
  const cases = [
    [503, "provider_not_configured", /not configured/],
    [429, "rate_limit", /rate limit/],
    [422, "consent_required", /Consent to share/],
    [409, "generation_in_progress", /already in progress/],
    [
      409,
      "generation_outcome_unknown",
      /outcome of this design request is unknown/,
    ],
    [504, "timeout", /outcome is unknown/],
    [409, "idempotency_conflict", /differs from the original/],
  ];
  for (const [status, code, pattern] of cases) {
    t.mock.method(globalThis, "fetch", async () =>
      Response.json(
        { code, message: "PRIVATE_PROVIDER_BODY sk-secret" },
        { status },
      ),
    );
    await assert.rejects(
      generateDesign(token, "project-a", designBody),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.equal(error.code, code);
        assert.match(error.message, pattern);
        assert.doesNotMatch(error.message, /PRIVATE|sk-secret/);
        return true;
      },
    );
    t.mock.restoreAll();
  }
});

test("design scoped mismatches are rejected safely", async (t) => {
  const payloads = [
    { ...designResult, project_id: "project-other" },
    { ...designResult, inventory_revision_id: "inventory-2" },
    {
      ...designResult,
      candidates: [
        {
          ...designResult.candidates[0],
          version: {
            ...designResult.candidates[0].version,
            inventory_revision_id: "inventory-2",
          },
        },
      ],
    },
  ];
  for (const payload of payloads) {
    t.mock.method(globalThis, "fetch", async () => Response.json(payload));
    await assert.rejects(
      generateDesign(token, "project-a", designBody),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "invalid_response");
        return true;
      },
    );
    t.mock.restoreAll();
  }
});

test("design cancellation aborts without leaking abort details", async (t) => {
  let requestSignal;
  t.mock.method(globalThis, "fetch", (path, options) => {
    requestSignal = options.signal;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("PRIVATE_ABORT_DETAIL", "AbortError")),
        { once: true },
      );
    });
  });
  const controller = new AbortController();
  const pending = generateDesign(
    token,
    "project-a",
    designBody,
    controller.signal,
  );
  controller.abort();
  await assert.rejects(pending, (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "cancelled");
    assert.doesNotMatch(error.message, /PRIVATE_ABORT_DETAIL/);
    return true;
  });
  assert.equal(requestSignal.aborted, true);
});

const diagnosisResult = {
  project_id: "project-a",
  revision_id: "inventory-1",
  media_id: "media-a",
  active_version_id: null,
  current_operation_id: null,
  diagnosis: {
    visible_observations: ["A tear is visible"],
    hypotheses: ["The slot may be weak"],
    questions_or_measurements: ["Measure the edge distance"],
    affected_ids: [],
    failure_type: "unknown",
  },
  diagnostics: { status: "ok", model: "muse-spark-test", elapsed_ms: 18 },
};

const diagnosisBody = {
  media_id: "media-a",
  expected_revision_id: "inventory-1",
  reported_problem: "The slot tore",
  provider_transfer_consented: true,
};

test("diagnosis request sends exactly the scoped body with caller auth", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(diagnosisResult);
  });
  const result = await requestDiagnosis(token, "project-a", diagnosisBody);
  assert.deepEqual(result, diagnosisResult);
  assert.equal(calls[0].path, "/api/projects/project-a/diagnose");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), diagnosisBody);
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
});

test("diagnosis photo-only invented affected IDs are rejected safely", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({
      ...diagnosisResult,
      diagnosis: { ...diagnosisResult.diagnosis, affected_ids: ["part-x"] },
    }),
  );
  await assert.rejects(
    requestDiagnosis(token, "project-a", diagnosisBody),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, "invalid_response");
      return true;
    },
  );
});

test("diagnosis scoped mismatches and provider errors are safe", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({ ...diagnosisResult, revision_id: "inventory-2" }),
  );
  await assert.rejects(
    requestDiagnosis(token, "project-a", diagnosisBody),
    (error) => error instanceof ApiError && error.code === "invalid_response",
  );
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "timeout", message: "PRIVATE_PROVIDER_BODY sk-secret" },
      { status: 504 },
    ),
  );
  await assert.rejects(
    requestDiagnosis(token, "project-a", diagnosisBody),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, "timeout");
      assert.doesNotMatch(error.message, /PRIVATE|sk-secret/);
      return true;
    },
  );
});

test("diagnosis cancellation aborts without leaking abort details", async (t) => {
  let requestSignal;
  t.mock.method(globalThis, "fetch", (path, options) => {
    requestSignal = options.signal;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("PRIVATE_ABORT_DETAIL", "AbortError")),
        { once: true },
      );
    });
  });
  const controller = new AbortController();
  const pending = requestDiagnosis(
    token,
    "project-a",
    diagnosisBody,
    controller.signal,
  );
  controller.abort();
  await assert.rejects(pending, (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "cancelled");
    assert.doesNotMatch(error.message, /PRIVATE_ABORT_DETAIL/);
    return true;
  });
  assert.equal(requestSignal.aborted, true);
});

const savedList = {
  projects: [
    {
      id: "project-a",
      goal: "A phone stand",
      revision_id: "inventory-1",
      inventory_confirmed: true,
      active_version_id: null,
    },
    {
      id: "project-b",
      goal: "Un soporte",
      revision_id: "inventory-2",
      inventory_confirmed: false,
      active_version_id: "version-1",
    },
  ],
  next_cursor: "project-b",
};

test("saved projects request sends exact auth and bounded pagination query", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(savedList);
  });
  const result = await listSavedProjects(token, {
    limit: 2,
    cursor: "project-0",
  });
  assert.deepEqual(result, savedList);
  assert.equal(calls[0].path, "/api/projects?limit=2&cursor=project-0");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.cache, "no-store");
  await assert.rejects(
    listSavedProjects(token, { limit: 51 }),
    (error) => error instanceof ApiError && error.code === "validation_error",
  );
  assert.equal(calls.length, 1);
});

test("saved projects mismatched, oversized and unordered shapes are rejected", async (t) => {
  const payloads = [
    { ...savedList, projects: [...savedList.projects, savedList.projects[1]] },
    { projects: [{ ...savedList.projects[0], goal: 42 }], next_cursor: null },
    {
      projects: [savedList.projects[1], savedList.projects[0]],
      next_cursor: null,
    },
    { projects: [], next_cursor: "project-b" },
    { projects: savedList.projects, next_cursor: "project-other" },
    { projects: savedList.projects, next_cursor: 7 },
  ];
  for (const payload of payloads) {
    t.mock.method(globalThis, "fetch", async () => Response.json(payload));
    await assert.rejects(
      listSavedProjects(token, { limit: 2 }),
      (error) => error instanceof ApiError && error.code === "invalid_response",
    );
    t.mock.restoreAll();
  }
});

test("saved projects errors and cancellation stay safe", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "PRIVATE_CODE", message: "PRIVATE_SERVER_TEXT" },
      { status: 401 },
    ),
  );
  await assert.rejects(listSavedProjects(token), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 401);
    assert.doesNotMatch(error.message, /PRIVATE/);
    return true;
  });
  t.mock.restoreAll();
  let requestSignal;
  t.mock.method(globalThis, "fetch", (path, options) => {
    requestSignal = options.signal;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("PRIVATE_ABORT_DETAIL", "AbortError")),
        { once: true },
      );
    });
  });
  const controller = new AbortController();
  const pending = listSavedProjects(token, {}, controller.signal);
  controller.abort();
  await assert.rejects(
    pending,
    (error) =>
      error instanceof ApiError &&
      error.code === "cancelled" &&
      !/PRIVATE/.test(error.message),
  );
  assert.equal(requestSignal.aborted, true);
});

const readinessResult = {
  project_id: "project-a",
  inventory_revision_id: "inventory-1",
  inventory_confirmed: false,
  status: "needs_input",
  missing_inputs: ["Confirm the saved inventory."],
  blockers: [{ code: "unsupported", message: "No profiles.", target_ids: [] }],
};

test("readiness request is scoped GET with caller auth and no body", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(readinessResult);
  });
  const result = await loadDesignReadiness(token, "project-a", "inventory-1");
  assert.deepEqual(result, readinessResult);
  assert.equal(calls[0].path, "/api/projects/project-a/designs/readiness");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.body, undefined);
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
});

test("readiness mismatched revision and inconsistent completeness are rejected", async (t) => {
  const payloads = [
    { ...readinessResult, project_id: "project-other" },
    { ...readinessResult, inventory_revision_id: "inventory-2" },
    { ...readinessResult, status: "inputs_complete" },
    { ...readinessResult, missing_inputs: "PRIVATE" },
    {
      ...readinessResult,
      blockers: [{ code: "unsupported", message: 9, target_ids: [] }],
    },
    {
      ...readinessResult,
      blockers: Array.from({ length: 33 }, () => ({
        code: "unsupported",
        message: "x",
        target_ids: [],
      })),
    },
  ];
  for (const payload of payloads) {
    t.mock.method(globalThis, "fetch", async () => Response.json(payload));
    await assert.rejects(
      loadDesignReadiness(token, "project-a", "inventory-1"),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "invalid_response");
        assert.doesNotMatch(error.message, /PRIVATE/);
        return true;
      },
    );
    t.mock.restoreAll();
  }
});

test("readiness errors and cancellation stay safe", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "not_found", message: "PRIVATE_SERVER_TEXT" },
      { status: 404 },
    ),
  );
  await assert.rejects(
    loadDesignReadiness(token, "project-a", "inventory-1"),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 404);
      assert.doesNotMatch(error.message, /PRIVATE/);
      return true;
    },
  );
  t.mock.restoreAll();
  let requestSignal;
  t.mock.method(globalThis, "fetch", (path, options) => {
    requestSignal = options.signal;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("PRIVATE_ABORT_DETAIL", "AbortError")),
        { once: true },
      );
    });
  });
  const controller = new AbortController();
  const pending = loadDesignReadiness(
    token,
    "project-a",
    "inventory-1",
    controller.signal,
  );
  controller.abort();
  await assert.rejects(
    pending,
    (error) =>
      error instanceof ApiError &&
      error.code === "cancelled" &&
      !/PRIVATE/.test(error.message),
  );
  assert.equal(requestSignal.aborted, true);
});

const handoffVersion = {
  project_id: "project-a",
  version_id: "version-a",
  plan: {
    parts: [{ id: "part-b" }, { id: "part-a" }],
    joints: [{ id: "joint-a" }],
    operations: [{ id: "operation-a" }],
    stocks: [{ id: "stock-a" }],
  },
};

function diagnosisFor(affectedIds, failureType = "torn_slot", overrides = {}) {
  return {
    project_id: "project-a",
    active_version_id: "version-a",
    diagnosis: {
      visible_observations: [],
      hypotheses: [],
      questions_or_measurements: [],
      affected_ids: affectedIds,
      failure_type: failureType,
    },
    ...overrides,
  };
}

test("repair handoff is built only for the matching project and active version", () => {
  const handoff = handoffFromDiagnosis(
    diagnosisFor([
      "joint-a",
      "part-a",
      "feature-a",
      "part-b",
      "part-a",
      "operation-a",
      "stock-a",
    ]),
    handoffVersion,
  );
  // Only part IDs survive, deduped in the diagnosis's original order;
  // joint, feature, operation and stock IDs are ignored.
  assert.deepEqual(handoff, {
    projectId: "project-a",
    versionId: "version-a",
    targetIds: ["part-a", "part-b"],
    failureType: "torn_slot",
    source: "muse_diagnosis",
  });
  assert.equal(
    handoffFromDiagnosis(
      diagnosisFor(["part-a"], "torn_slot", { project_id: "project-other" }),
      handoffVersion,
    ),
    null,
  );
  assert.equal(
    handoffFromDiagnosis(
      diagnosisFor(["part-a"], "torn_slot", { active_version_id: "version-b" }),
      handoffVersion,
    ),
    null,
  );
  assert.equal(
    handoffFromDiagnosis(
      diagnosisFor(["part-a"], "torn_slot", { active_version_id: null }),
      handoffVersion,
    ),
    null,
  );
  assert.equal(
    handoffFromDiagnosis(
      diagnosisFor(["part-a"], "torn_slot", { active_version_id: undefined }),
      handoffVersion,
    ),
    null,
  );
  assert.equal(
    handoffFromDiagnosis(
      diagnosisFor(["joint-a", "operation-a"]),
      handoffVersion,
    ),
    null,
  );
  assert.equal(handoffFromDiagnosis(diagnosisFor([]), handoffVersion), null);
});

test("isHandoffCurrent matches only the handoff project and version", () => {
  const handoff = handoffFromDiagnosis(
    diagnosisFor(["part-a"]),
    handoffVersion,
  );
  assert.equal(isHandoffCurrent(handoff, "project-a", "version-a"), true);
  assert.equal(isHandoffCurrent(handoff, "project-other", "version-a"), false);
  assert.equal(isHandoffCurrent(handoff, "project-a", "version-b"), false);
  assert.equal(isHandoffCurrent(null, "project-a", "version-a"), false);
  assert.equal(isHandoffCurrent(undefined, "project-a", "version-a"), false);
});

test("draftFromHandoff never picks a repair kind, stock or size from the failure type", () => {
  for (const failureType of [
    "torn_slot",
    "wrong_dimension",
    "missing_material",
    "damaged_part",
    "unstable",
    "unknown",
  ]) {
    const handoff = handoffFromDiagnosis(
      diagnosisFor(["part-a", "part-b"], failureType),
      handoffVersion,
    );
    assert.deepEqual(draftFromHandoff(handoff, "part-b"), {
      kind: "replace_part",
      targetId: "part-b",
      stockId: "",
      width: "",
      height: "",
      rationale: `From Muse diagnosis (unverified): ${failureType}`,
    });
  }
});

test("deadline also aborts a stalled response body", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(
    globalThis,
    "fetch",
    async (path, options) =>
      new Response(
        new ReadableStream({
          start(stream) {
            options.signal.addEventListener("abort", () =>
              stream.error(new DOMException("aborted", "AbortError")),
            );
          },
        }),
      ),
  );
  const pending = loadProject(token, "project-a");
  t.mock.timers.tick(30_000);
  await assert.rejects(pending, (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "request_timeout");
    return true;
  });
});
