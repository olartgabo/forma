import type { Stock } from "./generated/contracts";
import type {
  BuildRequirements,
  ActivationResult,
  PlanActivation,
  PlanList,
  PlanVersion,
  ProgressUpdate,
  ProgressSnapshot,
  ProgressResult,
  ProofSnapshot,
  CreateProject,
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

async function responseError(response: Response): Promise<ApiError> {
  let code = "request_failed";
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "code" in body) {
      const known = ["stale_version", "idempotency_conflict", "blocked"];
      if (typeof body.code === "string" && known.includes(body.code))
        code = body.code;
    }
  } catch {
    // Proxy failures may contain HTML; only local messages reach the UI.
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
    if (!response.ok) throw await responseError(response);
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
