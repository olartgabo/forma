export const EVIDENCE_PHOTO_DELETE_REASON =
  "This photo is linked to diagnosis or physical evidence, so it cannot be deleted. The evidence record keeps this photo.";

export const MATERIAL_PHOTO_DELETE_REASON =
  "Unlink from materials and save before deleting.";

export type PhotoDeletionState = {
  disabled: boolean;
  evidenceLinked: boolean;
  materialLinked: boolean;
  evidenceReason: string | null;
  materialReason: string | null;
};

export function photoDeletionState(
  photo: { evidence_linked?: boolean | null },
  options: { materialLinked: boolean; locked?: boolean },
): PhotoDeletionState {
  const evidenceLinked = photo.evidence_linked === true;
  const materialLinked = options.materialLinked === true;
  return {
    disabled: Boolean(options.locked) || evidenceLinked || materialLinked,
    evidenceLinked,
    materialLinked,
    evidenceReason: evidenceLinked ? EVIDENCE_PHOTO_DELETE_REASON : null,
    materialReason: materialLinked ? MATERIAL_PHOTO_DELETE_REASON : null,
  };
}

export function shouldApplyPhotoRefresh(input: {
  aborted: boolean;
  requestEpoch: number;
  currentEpoch: number;
  requestProjectId: string | null;
  currentProjectId: string | null;
  requestToken: string;
  currentToken: string;
}): boolean {
  return (
    !input.aborted &&
    input.requestEpoch === input.currentEpoch &&
    input.requestProjectId === input.currentProjectId &&
    input.requestProjectId !== null &&
    input.requestToken === input.currentToken
  );
}
