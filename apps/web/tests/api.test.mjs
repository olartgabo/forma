import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ApiError,
  activatePlan,
  createProject,
  deletePhoto,
  fetchPhoto,
  generateDesign,
  listPhotos,
  listPlans,
  loadPlan,
  loadProject,
  requestDiagnosis,
  requestIntakeObservation,
  saveInventory,
  uploadPhoto,
} from "../src/lib/api.ts";
import {
  editConstraint,
  emptyRequirements,
  requirementsError,
} from "../src/lib/build-requirements.ts";

const token = "synthetic-owner-credential";
const savedProject = {
  id: "project-a",
  goal: "A phone stand",
  revision_id: "inventory-1",
  stocks: [],
};

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
