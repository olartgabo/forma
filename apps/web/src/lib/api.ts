import type { Stock } from "./generated/contracts";
import type {
  BuildRequirements,
  ActivationResult,
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

async function responseError(
  response: Response,
  intake = false,
): Promise<ApiError> {
  let code = "request_failed";
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "code" in body) {
      const known = intake
        ? INTAKE_CODES
        : ["stale_version", "idempotency_conflict", "blocked"];
      if (typeof body.code === "string" && known.includes(body.code))
        code = body.code;
    }
  } catch {
    // Proxy failures may contain HTML; only local messages reach the UI.
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
    if (!response.ok) throw await responseError(response, intake);
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
