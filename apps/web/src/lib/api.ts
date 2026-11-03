import type { Stock } from "./generated/contracts";
import type {
  BuildRequirements,
  ActivationResult,
  AdaptCommitRequest,
  AdaptCommitResult,
  AdaptPreviewSet,
  AdaptSimulateRequest,
  DamageReport,
  DesignGenerateRequest,
  DesignGenerateResult,
  DesignReadiness,
  DiagnosisRequest,
  DiagnosisResult,
  FabricationReport,
  FabricationAssessment,
  PlanActivation,
  PlanList,
  PlanVersion,
  ProgressUpdate,
  ProgressSnapshot,
  ProgressResult,
  ProofSnapshot,
  CreateProject,
  IntakeRequest,
  IntakeResult,
  InventoryUpdate,
  MaterialReport,
  MediaList,
  MediaResult,
  Project,
  ProjectResult,
  ProviderStatusResponse,
  RepairProposeRequest,
  RepairProposeResult,
  RepairSearchRequest,
  RepairSearchResult,
  SavedProjectList,
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

const REPAIR_CODES = [...INTAKE_CODES];

const REPAIR_CODE_MESSAGES: Record<string, string> = {
  ...INTAKE_CODE_MESSAGES,
  consent_required:
    "Consent to send the reported problem, the diagnosis and saved project context to Meta is required before asking Muse.",
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
  repair = false,
): Promise<ApiError> {
  let code = "request_failed";
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "code" in body) {
      const known = repair
        ? REPAIR_CODES
        : design
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
  if (repair) {
    const repairStatusMessages: Record<number, string> = {
      401: "Check your development access key and reconnect.",
      403: "This access key cannot open this project.",
      404: "This project or active plan is unavailable. Reload the project.",
      409: "Saved project state changed. Reload the project before asking Muse again.",
      422:
        code === "consent_required"
          ? REPAIR_CODE_MESSAGES.consent_required
          : "The repair request could not be accepted. Check the reported problem and diagnosis, then try again.",
      429: REPAIR_CODE_MESSAGES.rate_limit,
      502: "The Muse request failed. Try again later.",
      503: REPAIR_CODE_MESSAGES.provider_not_configured,
      504: REPAIR_CODE_MESSAGES.timeout,
    };
    return new ApiError(
      response.status,
      code,
      REPAIR_CODE_MESSAGES[code] ??
        repairStatusMessages[response.status] ??
        "FORMA could not complete this request. Try again shortly.",
    );
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
          : "This change is blocked. Review the saved project and its linked evidence.",
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
  repair = false,
): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  // Runtime calls can use the gateway's bounded 120-second maximum, including
  // retries. Leave time for validation and persistence before the browser stops
  // waiting; ordinary storage requests retain their shorter deadline.
  const timeout = setTimeout(
    () => controller.abort(),
    intake || design || diagnosis || repair ? 130_000 : 30_000,
  );
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
      throw await responseError(response, intake, design, diagnosis, repair);
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

export type ProviderStatus = Omit<ProviderStatusResponse, "model"> & {
  model: string | null;
};

function checkedProviderStatus(value: unknown): ProviderStatus {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned a Muse provider status that could not be read. Try again.",
    );
  if (!isRecord(value)) throw invalid();
  if (typeof value.configured !== "boolean") throw invalid();
  if (
    value.model !== undefined &&
    value.model !== null &&
    typeof value.model !== "string"
  )
    throw invalid();
  return {
    configured: value.configured,
    model: typeof value.model === "string" ? value.model : null,
  };
}

export function getProviderStatus(
  token: string,
  signal?: AbortSignal,
): Promise<ProviderStatus> {
  return request(
    token,
    "/api/provider/status",
    { method: "GET" },
    async (response) => checkedProviderStatus(await json<unknown>(response)),
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
    async (response) => {
      const project = await json<Project>(response);
      if (project.id !== id) {
        throw new ApiError(
          response.status,
          "invalid_response",
          "FORMA returned a project that does not match the requested project. Reload and try again.",
        );
      }
      return project;
    },
    signal,
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function checkedSavedProjectList(
  value: unknown,
  limit: number,
): SavedProjectList {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned a saved project list that could not be read. Try again.",
    );
  if (!isRecord(value) || !Array.isArray(value.projects)) throw invalid();
  if (value.projects.length > limit) throw invalid();
  if (
    value.next_cursor !== null &&
    value.next_cursor !== undefined &&
    !isNonEmptyString(value.next_cursor)
  )
    throw invalid();
  if (value.projects.length === 0 && value.next_cursor) throw invalid();
  let previousId: string | null = null;
  for (const summary of value.projects) {
    if (
      !isRecord(summary) ||
      !isNonEmptyString(summary.id) ||
      typeof summary.goal !== "string" ||
      !isNonEmptyString(summary.revision_id) ||
      typeof summary.inventory_confirmed !== "boolean" ||
      (summary.active_version_id !== null &&
        summary.active_version_id !== undefined &&
        !isNonEmptyString(summary.active_version_id))
    )
      throw invalid();
    // The backend returns summaries in stable project-ID order.
    if (previousId !== null && summary.id <= previousId) throw invalid();
    previousId = summary.id;
  }
  if (
    isNonEmptyString(value.next_cursor) &&
    previousId !== null &&
    value.next_cursor !== previousId
  )
    throw invalid();
  return value as unknown as SavedProjectList;
}

export function listSavedProjects(
  token: string,
  options?: { limit?: number; cursor?: string | null },
  signal?: AbortSignal,
): Promise<SavedProjectList> {
  const limit = options?.limit ?? 20;
  const cursor = options?.cursor ?? null;
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    return Promise.reject(
      new ApiError(
        0,
        "validation_error",
        "Saved projects can be loaded in pages of 1 to 50.",
      ),
    );
  }
  if (cursor !== null && !isNonEmptyString(cursor)) {
    return Promise.reject(
      new ApiError(
        0,
        "validation_error",
        "The saved project page could not be identified. Reload the list.",
      ),
    );
  }
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) query.set("cursor", cursor);
  return request(
    token,
    `/api/projects?${query.toString()}`,
    { method: "GET" },
    async (response) =>
      checkedSavedProjectList(await json<unknown>(response), limit),
    signal,
  );
}

function checkedDesignReadiness(
  value: unknown,
  projectId: string,
  expectedRevision: string,
): DesignReadiness {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned an input checklist that does not match this project or inventory revision. Reload the project and try again.",
    );
  if (!isRecord(value)) throw invalid();
  if (
    value.project_id !== projectId ||
    value.inventory_revision_id !== expectedRevision ||
    typeof value.inventory_confirmed !== "boolean" ||
    !["inputs_complete", "needs_input"].includes(value.status as string) ||
    !isStringArray(value.missing_inputs) ||
    value.missing_inputs.length > 32 ||
    !Array.isArray(value.blockers) ||
    value.blockers.length > 32
  )
    throw invalid();
  // Checklist completeness is derived only from the missing-input list.
  if (
    (value.status === "inputs_complete") !==
    (value.missing_inputs.length === 0)
  )
    throw invalid();
  for (const blocker of value.blockers) {
    if (
      !isRecord(blocker) ||
      !isNonEmptyString(blocker.code) ||
      typeof blocker.message !== "string" ||
      (blocker.target_ids !== undefined && !isStringArray(blocker.target_ids))
    )
      throw invalid();
  }
  return value as unknown as DesignReadiness;
}

export function loadDesignReadiness(
  token: string,
  id: string,
  expectedRevision: string,
  signal?: AbortSignal,
): Promise<DesignReadiness> {
  return request(
    token,
    `${projectPath(id)}/designs/readiness`,
    { method: "GET" },
    async (response) =>
      checkedDesignReadiness(
        await json<unknown>(response),
        id,
        expectedRevision,
      ),
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

export function loadProgress(
  token: string,
  id: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<ProgressSnapshot> {
  return request(
    token,
    `${projectPath(id)}/versions/${encodeURIComponent(versionId)}/progress`,
    { method: "GET" },
    json<ProgressSnapshot>,
    signal,
  );
}

export function recordProgress(
  token: string,
  id: string,
  body: ProgressUpdate,
  signal?: AbortSignal,
): Promise<ProgressResult> {
  return request(
    token,
    `${projectPath(id)}/events`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<ProgressResult>,
    signal,
  );
}

export function reportDamage(
  token: string,
  id: string,
  body: DamageReport,
  signal?: AbortSignal,
): Promise<ProgressResult> {
  return request(
    token,
    `${projectPath(id)}/damage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<ProgressResult>,
    signal,
  );
}

export function reportMaterial(
  token: string,
  id: string,
  body: MaterialReport,
  signal?: AbortSignal,
): Promise<ProgressResult> {
  return request(
    token,
    `${projectPath(id)}/materials`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<ProgressResult>,
    signal,
  );
}

export function simulateRepairs(
  token: string,
  id: string,
  body: AdaptSimulateRequest,
  signal?: AbortSignal,
): Promise<AdaptPreviewSet> {
  return request(
    token,
    `${projectPath(id)}/adapt/simulate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<AdaptPreviewSet>,
    signal,
  );
}

export async function searchRepairs(
  token: string,
  id: string,
  body: RepairSearchRequest,
  signal?: AbortSignal,
): Promise<RepairSearchResult> {
  try {
    return await request(
      token,
      `${projectPath(id)}/repairs/search`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      json<RepairSearchResult>,
      signal,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 409)
      throw new ApiError(
        409,
        error.code,
        error.code === "stale_version"
          ? "The plan or its recorded history changed. Reload recorded work and search again."
          : error.code === "idempotency_conflict"
            ? "This retry differs from the original search. Search again."
            : "There is nothing to search for yet. Report damage or a failed check, or choose a part in the repair form.",
      );
    throw error;
  }
}

export function approveRepair(
  token: string,
  id: string,
  body: AdaptCommitRequest,
  signal?: AbortSignal,
): Promise<AdaptCommitResult> {
  return request(
    token,
    `${projectPath(id)}/adapt/commit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    json<AdaptCommitResult>,
    signal,
  );
}

const FABRICATION_STATUSES = [
  "ready",
  "blocked",
  "complete",
  "history_conflict",
];

function checkedFabricationReport(
  value: unknown,
  projectId: string,
  versionId: string,
  assessment?: FabricationAssessment,
): FabricationReport {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned a step report for a different project or plan version. Reload the manual and try again.",
    );
  if (
    !isRecord(value) ||
    !isRecord(value.snapshot) ||
    value.snapshot.project_id !== projectId ||
    value.snapshot.version_id !== versionId ||
    typeof value.snapshot.inputs_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.snapshot.inputs_sha256) ||
    (assessment !== undefined &&
      (value.snapshot.inventory_revision_id !==
        assessment.expected_inventory_revision_id ||
        value.snapshot.last_event_id !== assessment.expected_last_event_id)) ||
    !FABRICATION_STATUSES.includes(value.status as string) ||
    !Array.isArray(value.operations) ||
    !Array.isArray(value.supported_order) ||
    !Array.isArray(value.blockers) ||
    value.observed_usability !== "not_assessed"
  )
    throw invalid();
  return value as unknown as FabricationReport;
}

async function fabricationRequest(
  token: string,
  path: string,
  projectId: string,
  versionId: string,
  conflict: string,
  signal?: AbortSignal,
  assessment?: FabricationAssessment,
): Promise<FabricationReport> {
  try {
    return await request(
      token,
      path,
      assessment === undefined
        ? { method: "GET" }
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(assessment),
          },
      async (response) =>
        checkedFabricationReport(
          await json<unknown>(response),
          projectId,
          versionId,
          assessment,
        ),
      signal,
    );
  } catch (error) {
    if (
      assessment !== undefined &&
      error instanceof ApiError &&
      error.status === 422
    )
      throw new ApiError(
        422,
        error.code,
        "These report confirmations could not be accepted. Check tool names and measured lengths; record material loss or reconcile a different balance before continuing.",
      );
    if (error instanceof ApiError && error.status === 409)
      throw new ApiError(
        409,
        error.code,
        error.code === "blocked"
          ? "This saved build cannot be assessed under the supported report limits. Review its history and required inputs."
          : conflict,
      );
    if (error instanceof ApiError && error.status === 404)
      throw new ApiError(
        404,
        error.code,
        "This plan or repair preview is unavailable. Reload the project.",
      );
    throw error;
  }
}

export function loadFabricationReport(
  token: string,
  id: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<FabricationReport> {
  return fabricationRequest(
    token,
    `${projectPath(id)}/versions/${encodeURIComponent(versionId)}/fabrication`,
    id,
    versionId,
    "The active plan or its recorded history changed. Reload the manual to see the current next step.",
    signal,
  );
}

export function loadPreviewFabricationReport(
  token: string,
  id: string,
  previewId: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<FabricationReport> {
  return fabricationRequest(
    token,
    `${projectPath(id)}/adapt/previews/${encodeURIComponent(previewId)}/fabrication`,
    id,
    versionId,
    "Physical history changed after this repair preview. Simulate the repair again to see its next step.",
    signal,
  );
}

export function assessFabricationReport(
  token: string,
  id: string,
  versionId: string,
  body: FabricationAssessment,
  signal?: AbortSignal,
): Promise<FabricationReport> {
  return fabricationRequest(
    token,
    `${projectPath(id)}/versions/${encodeURIComponent(versionId)}/fabrication/assess`,
    id,
    versionId,
    "The active plan, inventory or recorded history changed. Reload the manual and confirm fresh inputs for the current next step.",
    signal,
    body,
  );
}

export function loadProof(
  token: string,
  id: string,
  signal?: AbortSignal,
): Promise<ProofSnapshot> {
  return request(
    token,
    `${projectPath(id)}/proof`,
    { method: "GET" },
    json<ProofSnapshot>,
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

const REPAIR_PATCH_KINDS = [
  "resize_part",
  "replace_joint_profile",
  "replace_part",
  "change_angle",
];

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actual = Object.keys(value);
  return (
    actual.length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function isBoundedText(value: unknown): value is string {
  // Server contract (Text) is raw length 1..2000 with no whitespace stripping.
  return typeof value === "string" && value.length > 0 && value.length <= 2000;
}

function isNullableId(value: unknown): boolean {
  return value === null || isNonEmptyString(value);
}

function isNullablePositive(value: unknown): boolean {
  return (
    value === null ||
    (typeof value === "number" && Number.isFinite(value) && value > 0)
  );
}

function checkedRepairProposeResult(
  value: unknown,
  projectId: string,
  body: RepairProposeRequest,
): RepairProposeResult {
  const invalid = () =>
    new ApiError(
      200,
      "invalid_response",
      "FORMA returned repair proposals that do not match this project or version. Reload the project and try again.",
    );
  if (!isRecord(value)) throw invalid();
  if (
    !hasExactKeys(value, [
      "project_id",
      "base_version_id",
      "base_last_event_id",
      "candidates",
      "questions",
      "diagnostics",
    ]) ||
    value.project_id !== projectId ||
    value.base_version_id !== body.expected_version_id ||
    value.base_last_event_id !== body.expected_last_event_id ||
    !Array.isArray(value.candidates) ||
    value.candidates.length > 3 ||
    !Array.isArray(value.questions) ||
    value.questions.length > 8 ||
    !value.questions.every(isBoundedText) ||
    !isRecord(value.diagnostics) ||
    !Object.keys(value.diagnostics).every((key) =>
      ["status", "model", "elapsed_ms", "usage"].includes(key),
    ) ||
    value.diagnostics.status !== "ok" ||
    !isNonEmptyString(value.diagnostics.model) ||
    value.diagnostics.model.length > 80 ||
    typeof value.diagnostics.elapsed_ms !== "number" ||
    !Number.isFinite(value.diagnostics.elapsed_ms) ||
    value.diagnostics.elapsed_ms < 0
  )
    throw invalid();
  const usage = value.diagnostics.usage;
  if (usage !== undefined && usage !== null) {
    if (
      !isRecord(usage) ||
      !Object.keys(usage).every((key) =>
        ["model_calls", "input_tokens", "output_tokens"].includes(key),
      ) ||
      typeof usage.model_calls !== "number" ||
      !Number.isSafeInteger(usage.model_calls) ||
      usage.model_calls < 0 ||
      usage.model_calls > 16 ||
      (usage.input_tokens !== undefined &&
        usage.input_tokens !== null &&
        (typeof usage.input_tokens !== "number" ||
          !Number.isSafeInteger(usage.input_tokens) ||
          usage.input_tokens < 0 ||
          usage.input_tokens > 16_000_000_000)) ||
      (usage.output_tokens !== undefined &&
        usage.output_tokens !== null &&
        (typeof usage.output_tokens !== "number" ||
          !Number.isSafeInteger(usage.output_tokens) ||
          usage.output_tokens < 0 ||
          usage.output_tokens > 16_000_000_000))
    )
      throw invalid();
  }
  const seen = new Set<string>();
  for (const candidate of value.candidates as unknown[]) {
    if (
      !isRecord(candidate) ||
      !hasExactKeys(candidate, [
        "id",
        "base_version_id",
        "kind",
        "target_id",
        "replacement_stock_id",
        "replacement_profile_id",
        "width_mm",
        "height_mm",
        "angle_deg",
        "rationale",
      ]) ||
      !isNonEmptyString(candidate.id) ||
      seen.has(candidate.id) ||
      candidate.base_version_id !== body.expected_version_id ||
      !REPAIR_PATCH_KINDS.includes(candidate.kind as string) ||
      !isNonEmptyString(candidate.target_id) ||
      !isBoundedText(candidate.rationale) ||
      !isNullableId(candidate.replacement_stock_id) ||
      !isNullableId(candidate.replacement_profile_id) ||
      !isNullablePositive(candidate.width_mm) ||
      !isNullablePositive(candidate.height_mm) ||
      !isNullablePositive(candidate.angle_deg) ||
      (typeof candidate.angle_deg === "number" && candidate.angle_deg >= 90)
    )
      throw invalid();
    seen.add(candidate.id as string);
  }
  return value as unknown as RepairProposeResult;
}

export function proposeRepairs(
  token: string,
  id: string,
  body: RepairProposeRequest,
  signal?: AbortSignal,
): Promise<RepairProposeResult> {
  return request(
    token,
    `${projectPath(id)}/repairs/propose`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    async (response) =>
      checkedRepairProposeResult(await json<unknown>(response), id, body),
    signal,
    false,
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
