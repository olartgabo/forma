import type { Media, ProgressSnapshot } from "./generated/api-contracts";
import type { Evidence } from "./generated/contracts";

export type DiagnosisFocus = {
  projectId: string;
  versionId: string;
  operationId: string;
  mediaId: string | null;
  nonce: string;
};

export function createDiagnosisFocus(input: {
  projectId: string;
  versionId: string;
  operationId: string;
  mediaId?: string | null;
  nonce?: string;
}): DiagnosisFocus {
  return {
    projectId: input.projectId,
    versionId: input.versionId,
    operationId: input.operationId,
    mediaId: input.mediaId ?? null,
    nonce: input.nonce ?? crypto.randomUUID(),
  };
}

type PhotoRef = Pick<Media, "id"> | string;

function matchesVersion(
  progress: ProgressSnapshot | null | undefined,
  expectedVersionId?: string,
): progress is ProgressSnapshot {
  if (!progress) return false;
  if (
    expectedVersionId !== undefined &&
    progress.version_id !== expectedVersionId
  )
    return false;
  return true;
}

function forOperation(evidence: Evidence, operationId: string): boolean {
  return (evidence.operation_ids ?? []).includes(operationId);
}

// Newest first by recorded_at. Ties (and invalid dates) fall back to array
// order deterministically: a later array index is treated as newer, matching
// the backend's insertion-order history.
function newestFirst(evidence: readonly Evidence[]): Evidence[] {
  return evidence
    .map((item, index) => {
      const parsed = Date.parse(item.recorded_at);
      return { item, index, time: Number.isNaN(parsed) ? null : parsed };
    })
    .sort((left, right) => {
      if (left.time !== null && right.time !== null && left.time !== right.time)
        return right.time - left.time;
      if (left.time !== null && right.time === null) return -1;
      if (left.time === null && right.time !== null) return 1;
      return right.index - left.index;
    })
    .map(({ item }) => item);
}

function failedEvidence(
  progress: ProgressSnapshot | null | undefined,
  operationId: string,
  expectedVersionId?: string,
): Evidence[] {
  if (!matchesVersion(progress, expectedVersionId)) return [];
  return (progress.evidence ?? []).filter(
    (item) =>
      item.kind === "photo" &&
      item.verification_state === "failed" &&
      forOperation(item, operationId),
  );
}

export function selectFailedCheckPhoto(
  progress: ProgressSnapshot | null | undefined,
  operationId: string,
  photos: readonly PhotoRef[],
  expectedVersionId?: string,
): string | null {
  const available = new Set(
    (photos ?? []).map((photo) =>
      typeof photo === "string" ? photo : photo.id,
    ),
  );
  for (const item of newestFirst(
    failedEvidence(progress, operationId, expectedVersionId),
  )) {
    if (item.asset_id && available.has(item.asset_id)) return item.asset_id;
  }
  return null;
}

export function hasFailedCheck(
  progress: ProgressSnapshot | null | undefined,
  operationId: string,
  expectedVersionId?: string,
): boolean {
  if (!matchesVersion(progress, expectedVersionId)) return false;
  if ((progress.failed_operation_ids ?? []).includes(operationId)) return true;
  return failedEvidence(progress, operationId, expectedVersionId).length > 0;
}

export function latestDiagnosisEvidence(
  progress: ProgressSnapshot | null | undefined,
  operationId: string,
  limit = 3,
  expectedVersionId?: string,
): Evidence[] {
  if (!matchesVersion(progress, expectedVersionId)) return [];
  const capped = Number.isFinite(limit) ? Math.max(0, Math.trunc(limit)) : 3;
  if (capped === 0) return [];
  const diagnoses = (progress.evidence ?? []).filter(
    (item) =>
      item.kind === "model_interpretation" &&
      item.verification_state !== "invalidated" &&
      forOperation(item, operationId),
  );
  return newestFirst(diagnoses).slice(0, capped);
}
