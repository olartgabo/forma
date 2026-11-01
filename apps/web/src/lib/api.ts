import type { Stock } from "./generated/contracts";
import type {
  BuildRequirements,
  ActivationResult,
  DesignGenerateRequest,
  DesignGenerateResult,
  DiagnosisRequest,
  DiagnosisResult,
  PlanActivation,
  PlanList,
  PlanVersion,
  CreateProject,
  IntakeRequest,
  IntakeResult,
  InventoryUpdate,
  MediaList,
  MediaResult,
  Project,
  ProjectResult,
} from "./generated/api-contracts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const INTAKE_CODES = [
  "validation_error",
  "not_found",
  "stale_version",
  "consent_required",
  "provider_not_configured",
  "provider_authentication",
  "access_denied",
  "rate_limit",
  "timeout",
  "network_error",
  "invalid_response",
  "provider_http_error",
  "provider_error",
];

const INTAKE_CODE_MESSAGES: Record<string, string> = {
  provider_not_configured:
    "Muse is not configured on the server. Ask the project operator to configure it, then try again.",
  provider_authentication:
    "The server Muse credential was rejected. Ask the project operator to check it, then try again.",
  access_denied:
    "Muse denied access to the configured model. Ask the project operator to check access, then try again.",
  rate_limit: "Muse rate limit reached. Wait a while, then try again.",
  timeout: "The Muse request timed out. Try again later.",
  network_error: "Muse could not be reached from the server. Try again later.",
  invalid_response: "Muse returned an unusable response. Try again.",
  consent_required:
    "Consent to send the selected photo and saved project goal to Meta is required before asking Muse.",
  stale_version:
    "Inventory changed in another session. Reload the project before asking Muse again.",
  provider_http_error: "The Muse request failed. Try again later.",
  provider_error: "The Muse request failed. Try again later.",
  not_found:
    "This project or photo is unavailable. Check the project ID or reload.",
};

const DIAGNOSIS_CODES = [...INTAKE_CODES];

const DIAGNOSIS_CODE_MESSAGES: Record<string, string> = {
  ...INTAKE_CODE_MESSAGES,
  consent_required:
    "Consent to send the selected photo, your reported problem and saved project context to Meta is required before asking Muse.",
  stale_version:
    "Saved project state changed in another session. Reload the project before asking Muse again.",
};

const DESIGN_CODES = [
  ...INTAKE_CODES,
  "blocked",
  "idempotency_conflict",
  "generation_in_progress",
  "generation_outcome_unknown",
];

const DESIGN_CODE_MESSAGES: Record<string, string> = {
  ...INTAKE_CODE_MESSAGES,
  consent_required:
    "Consent to share the saved project context with Meta is required before generating designs.",
  stale_version:
    "Inventory changed in another session. Reload the project before generating designs again.",
  blocked:
    "Design generation is blocked for this project. Reload the project and check saved previews.",
  idempotency_conflict:
    "This retry differs from the original design request. Start a new request after checking saved previews.",
  generation_in_progress:
    "This design request is already in progress. Check saved previews before retrying.",
  generation_outcome_unknown:
    "The outcome of this design request is unknown. Check saved previews before starting a new request.",
  timeout:
    "The Muse request timed out and its outcome is unknown. Check saved previews before starting a new request.",
  network_error:
    "Muse could not be reached and the outcome of this design request is unknown. Check saved previews before starting a new request.",
  not_found: "This project is unavailable. Check the project ID or reload.",
};

async function responseError(
  response: Response,
  intake = false,
  design = false,
  diagnosis = false,
): Promise<ApiError> {
  let code = "request_failed";
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "code" in body) {
      const known = design
        ? DESIGN_CODES
        : diagnosis
          ? DIAGNOSIS_CODES
          : intake
            ? INTAKE_CODES
            : ["stale_version", "idempotency_conflict", "blocked"];
      if (typeof body.code === "string" && known.includes(body.code))
        code = body.code;
    }
  } catch {
    // Proxy failures may contain HTML; only local messages reach the UI.
  }
  if (diagnosis) {
    const diagnosisStatusMessages: Record<number, string> = {
      401: "Check your development access key and reconnect.",
      403: "This access key cannot open this project.",
      404: "This project, photo or active plan is unavailable. Reload the project.",
      409: "Saved project state changed. Reload the project before asking Muse again.",
      413: "The selected photo is too large for Muse. Choose a saved JPEG or PNG photo of 5,000,000 bytes or smaller.",
      415: "Muse can only read JPEG or PNG photos. Choose a saved JPEG or PNG photo for this project.",
      422:
        code === "consent_required"
          ? DIAGNOSIS_CODE_MESSAGES.consent_required
          : "The diagnosis request could not be accepted. Check the reported problem and current step, then try again.",
      429: DIAGNOSIS_CODE_MESSAGES.rate_limit,
      502: "The Muse request failed. Try again later.",
      503: DIAGNOSIS_CODE_MESSAGES.provider_not_configured,
      504: DIAGNOSIS_CODE_MESSAGES.timeout,
    };
    return new ApiError(
      response.status,
      code,
      DIAGNOSIS_CODE_MESSAGES[code] ??
        diagnosisStatusMessages[response.status] ??
        "FORMA could not complete this request. Try again shortly.",
    );
  }
  if (design) {
    const designStatusMessages: Record<number, string> = {
      401: "Check your development access key and reconnect.",
      403: "This access key cannot open this project.",
      404: DESIGN_CODE_MESSAGES.not_found,
      409:
        DESIGN_CODE_MESSAGES[code] ??
        "This design request conflicts with saved state. Reload and check saved previews.",
      422:
        code === "consent_required"
          ? DESIGN_CODE_MESSAGES.consent_required
          : "The design request could not be accepted. Check the saved project and try again.",
      429: DESIGN_CODE_MESSAGES.rate_limit,
      502: "The Muse request failed. Try again later.",
      503: DESIGN_CODE_MESSAGES.provider_not_configured,
      504: DESIGN_CODE_MESSAGES.timeout,
    };
    return new ApiError(
      response.status,
      code,
      DESIGN_CODE_MESSAGES[code] ??
        designStatusMessages[response.status] ??
        "FORMA could not complete this request. Try again shortly.",
    );
  }
  if (intake) {
    const intakeStatusMessages: Record<number, string> = {
      401: "Check your development access key and reconnect.",
      403: "This access key cannot open this project.",
      404: "This project or photo is unavailable. Check the project ID or reload.",
      409: "Inventory changed in another session. Reload the project before asking Muse again.",
      413: "The selected photo is too large for Muse. Choose a saved JPEG or PNG photo of 5,000,000 bytes or smaller.",
      415: "Muse can only read JPEG or PNG photos. Choose a saved JPEG or PNG photo for this project.",
      422:
        code === "consent_required"
          ? INTAKE_CODE_MESSAGES.consent_required
          : "The selected photo could not be accepted for Muse. Choose a saved JPEG or PNG photo of 5,000,000 bytes or smaller.",
      429: INTAKE_CODE_MESSAGES.rate_limit,
      502: "The Muse request failed. Try again later.",
      503: INTAKE_CODE_MESSAGES.provider_not_configured,
      504: INTAKE_CODE_MESSAGES.timeout,
    };
    return new ApiError(
      response.status,
      code,
      INTAKE_CODE_MESSAGES[code] ??
        intakeStatusMessages[response.status] ??
        "FORMA could not complete this request. Try again shortly.",
    );
  }
  const messages: Record<number, string> = {
    401: "Check your development access key and reconnect.",
    403: "This access key cannot open this project.",
    404: "This project or photo is unavailable. Check the project ID or reload.",
    409:
      code === "stale_version"
        ? "Materials or requirements changed in another session. Reload before saving again."
        : code === "idempotency_conflict"
          ? "This retry differs from the original request. Review your changes and try again."
          : "This change is blocked. Remove photo references or reload the project.",
    413: "The photo is too large. Choose an image smaller than 8 MiB and 20 million pixels.",
    415: "Choose a JPEG, PNG or WebP photo.",
    422: "Some details could not be accepted. Check your measurements and photo, then try again.",
  };
  return new ApiError(
    response.status,
    code,
    messages[response.status] ??
      "FORMA could not complete this request. Try again shortly.",
  );
}

async function request<T>(
  token: string,
  path: string,
  init: RequestInit,
  read: (response: Response) => Promise<T>,
  signal?: AbortSignal,
  intake = false,
  design = false,
  diagnosis = false,
): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(path, {
      ...init,
      headers,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal: controller.signal,
    });
    if (!response.ok)
      throw await responseError(response, intake, design, diagnosis);
    return await read(response);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted) {
      throw new ApiError(
        0,
        signal?.aborted ? "cancelled" : "request_timeout",
        signal?.aborted
          ? "Request cancelled."
          : "The request took too long. Retry to check whether your changes were saved.",
      );
    }
    throw new ApiError(
      0,
      "connection_failed",
      "Could not reach FORMA. Check the API connection and try again.",
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
}

async function json<T>(response: Response): Promise<T> {
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    throw new ApiError(
      response.status,
      "invalid_response",
      "FORMA returned an unreadable response. Retry or reload the project.",
    );
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ApiError(
      response.status,
      "invalid_response",
      "FORMA returned an unreadable response. Retry or reload the project.",
    );
  }
  return value as T;
}

function projectPath(id: string): string {
  return `/api/projects/${encodeURIComponent(id)}`;
}

export function createProject(
  token: string,
  goal: string,
  key: string,
  signal?: AbortSignal,
): Promise<ProjectResult> {
  const body: CreateProject = { goal, idempotency_key: key };
  return request(
    token,
    "/api/projects",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<ProjectResult>,
    signal,
  );
}

export function loadProject(
  token: string,
  id: string,
  signal?: AbortSignal,
): Promise<Project> {
  return request(
    token,
    projectPath(id),
    { method: "GET" },
    json<Project>,
    signal,
  );
}

export function saveInventory(
  token: string,
  id: string,
  stocks: ReadonlyArray<Stock>,
  expectedRevision: string,
  key: string,
  signal?: AbortSignal,
  requirements?: BuildRequirements | null,
): Promise<ProjectResult> {
  const body: InventoryUpdate = {
    stocks,
    expected_revision_id: expectedRevision,
    idempotency_key: key,
    user_confirmed: true,
    ...(requirements !== undefined ? { requirements } : {}),
  };
  return request(
    token,
    `${projectPath(id)}/inventory`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<ProjectResult>,
    signal,
  );
}

export function listPlans(
  token: string,
  id: string,
  signal?: AbortSignal,
): Promise<PlanList> {
  return request(
    token,
    `${projectPath(id)}/plans`,
    { method: "GET" },
    json<PlanList>,
    signal,
  );
}

export function loadPlan(
  token: string,
  id: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<PlanVersion> {
  return request(
    token,
    `${projectPath(id)}/versions/${encodeURIComponent(versionId)}`,
    { method: "GET" },
    json<PlanVersion>,
    signal,
  );
}

export function activatePlan(
  token: string,
  id: string,
  versionId: string,
  body: PlanActivation,
  signal?: AbortSignal,
): Promise<ActivationResult> {
  return request(
    token,
    `${projectPath(id)}/plans/${encodeURIComponent(versionId)}/activate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<ActivationResult>,
    signal,
  );
}

export function uploadPhoto(
  token: string,
  id: string,
  file: File,
  key: string,
  signal?: AbortSignal,
): Promise<MediaResult> {
  return request(
    token,
    `${projectPath(id)}/media`,
    {
      method: "POST",
      headers: { "Content-Type": file.type, "Idempotency-Key": key },
      body: file,
    },
    json<MediaResult>,
    signal,
  );
}

export function fetchPhoto(
  token: string,
  id: string,
  mediaId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  return request(
    token,
    `${projectPath(id)}/media/${encodeURIComponent(mediaId)}`,
    { method: "GET" },
    (response) => response.blob(),
    signal,
  );
}

export function listPhotos(
  token: string,
  id: string,
  signal?: AbortSignal,
): Promise<MediaList> {
  return request(
    token,
    `${projectPath(id)}/media`,
    { method: "GET" },
    json<MediaList>,
    signal,
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function checkedIntakeResult(
  value: unknown,
  projectId: string,
  revisionId: string,
  mediaId: string,
): IntakeResult {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned an intake result that does not match this project, revision or photo. Reload the project and try again.",
    );
  if (!isRecord(value)) throw invalid();
  if (
    value.project_id !== projectId ||
    value.revision_id !== revisionId ||
    value.media_id !== mediaId ||
    !isRecord(value.observation) ||
    !isStringArray(value.observation.labels) ||
    !isStringArray(value.observation.questions) ||
    value.observation.measurement_source !== "unknown" ||
    !isRecord(value.diagnostics) ||
    value.diagnostics.status !== "ok" ||
    typeof value.diagnostics.model !== "string" ||
    value.diagnostics.model.length === 0 ||
    typeof value.diagnostics.elapsed_ms !== "number" ||
    !Number.isFinite(value.diagnostics.elapsed_ms) ||
    value.diagnostics.elapsed_ms < 0
  )
    throw invalid();
  return value as unknown as IntakeResult;
}

export function requestIntakeObservation(
  token: string,
  id: string,
  mediaId: string,
  expectedRevision: string,
  signal?: AbortSignal,
): Promise<IntakeResult> {
  const body: IntakeRequest = {
    media_id: mediaId,
    expected_revision_id: expectedRevision,
    provider_transfer_consented: true,
  };
  return request(
    token,
    `${projectPath(id)}/intake`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    async (response) =>
      checkedIntakeResult(
        await json<unknown>(response),
        id,
        expectedRevision,
        mediaId,
      ),
    signal,
    true,
  );
}

function checkedDesignResult(
  value: unknown,
  projectId: string,
  revisionId: string,
): DesignGenerateResult {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned a design result that does not match this project or inventory revision. Check saved previews and reload the project.",
    );
  if (!isRecord(value)) throw invalid();
  if (
    value.project_id !== projectId ||
    value.inventory_revision_id !== revisionId ||
    !["proposed", "needs_measurement", "blocked"].includes(
      value.status as string,
    ) ||
    !Array.isArray(value.candidates) ||
    !isStringArray(value.questions) ||
    !Array.isArray(value.blockers) ||
    !isRecord(value.diagnostics) ||
    value.diagnostics.status !== "ok" ||
    typeof value.diagnostics.model !== "string" ||
    value.diagnostics.model.length === 0 ||
    typeof value.diagnostics.elapsed_ms !== "number" ||
    !Number.isFinite(value.diagnostics.elapsed_ms) ||
    value.diagnostics.elapsed_ms < 0 ||
    typeof value.diagnostics.model_rounds !== "number" ||
    typeof value.diagnostics.tool_executions !== "number"
  )
    throw invalid();
  for (const candidate of value.candidates) {
    if (
      !isRecord(candidate) ||
      typeof candidate.candidate_id !== "string" ||
      !["accepted", "blocked", "needs_measurement", "unsupported"].includes(
        candidate.status as string,
      ) ||
      !Array.isArray(candidate.blockers)
    )
      throw invalid();
    if (candidate.version !== null && candidate.version !== undefined) {
      if (
        !isRecord(candidate.version) ||
        candidate.version.project_id !== projectId ||
        candidate.version.inventory_revision_id !== revisionId ||
        typeof candidate.version.version_id !== "string" ||
        candidate.version.candidate_id !== candidate.candidate_id
      )
        throw invalid();
    }
    for (const blocker of candidate.blockers) {
      if (
        !isRecord(blocker) ||
        typeof blocker.code !== "string" ||
        typeof blocker.message !== "string"
      )
        throw invalid();
    }
  }
  for (const blocker of value.blockers) {
    if (
      !isRecord(blocker) ||
      typeof blocker.code !== "string" ||
      typeof blocker.message !== "string"
    )
      throw invalid();
  }
  return value as unknown as DesignGenerateResult;
}

export function generateDesign(
  token: string,
  id: string,
  body: DesignGenerateRequest,
  signal?: AbortSignal,
): Promise<DesignGenerateResult> {
  return request(
    token,
    `${projectPath(id)}/designs/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    async (response) =>
      checkedDesignResult(
        await json<unknown>(response),
        id,
        body.expected_revision_id,
      ),
    signal,
    false,
    true,
  );
}

const FAILURE_TYPES = [
  "torn_slot",
  "wrong_dimension",
  "missing_material",
  "damaged_part",
  "unstable",
  "unknown",
];

function checkedDiagnosisResult(
  value: unknown,
  projectId: string,
  revisionId: string,
  mediaId: string,
  activeVersionId: string | null,
  operationId: string | null,
): DiagnosisResult {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned a diagnosis that does not match this project, revision, photo or active step. Reload the project and try again.",
    );
  if (!isRecord(value)) throw invalid();
  if (
    value.project_id !== projectId ||
    value.revision_id !== revisionId ||
    value.media_id !== mediaId ||
    (value.active_version_id ?? null) !== activeVersionId ||
    (value.current_operation_id ?? null) !== operationId ||
    !isRecord(value.diagnosis) ||
    !isStringArray(value.diagnosis.visible_observations) ||
    !isStringArray(value.diagnosis.hypotheses) ||
    !isStringArray(value.diagnosis.questions_or_measurements) ||
    !isStringArray(value.diagnosis.affected_ids) ||
    !FAILURE_TYPES.includes(value.diagnosis.failure_type as string) ||
    !isRecord(value.diagnostics) ||
    value.diagnostics.status !== "ok" ||
    typeof value.diagnostics.model !== "string" ||
    value.diagnostics.model.length === 0 ||
    typeof value.diagnostics.elapsed_ms !== "number" ||
    !Number.isFinite(value.diagnostics.elapsed_ms) ||
    value.diagnostics.elapsed_ms < 0
  )
    throw invalid();
  if (activeVersionId === null && value.diagnosis.affected_ids.length !== 0)
    throw invalid();
  return value as unknown as DiagnosisResult;
}

export function requestDiagnosis(
  token: string,
  id: string,
  body: DiagnosisRequest,
  signal?: AbortSignal,
): Promise<DiagnosisResult> {
  return request(
    token,
    `${projectPath(id)}/diagnose`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    async (response) =>
      checkedDiagnosisResult(
        await json<unknown>(response),
        id,
        body.expected_revision_id,
        body.media_id,
        body.expected_active_version_id ?? null,
        body.current_operation_id ?? null,
      ),
    signal,
    false,
    false,
    true,
  );
}

export async function deletePhoto(
  token: string,
  id: string,
  mediaId: string,
  key: string,
  signal?: AbortSignal,
): Promise<void> {
  await request(
    token,
    `${projectPath(id)}/media/${encodeURIComponent(mediaId)}`,
    {
      method: "DELETE",
      headers: { "Idempotency-Key": key },
    },
    async () => undefined,
    signal,
  );
}
