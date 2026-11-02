import type { DiagnosisResult, PlanVersion } from "./generated/api-contracts";
import type { DiagnosisProposal } from "./generated/contracts";

export type RepairHandoff = {
  projectId: string;
  versionId: string;
  targetIds: readonly string[];
  failureType: DiagnosisProposal["failure_type"];
  source: "muse_diagnosis";
};

export type RepairDraftFields = {
  kind: "replace_part" | "resize_part";
  targetId: string;
  stockId: string;
  width: string;
  height: string;
  rationale: string;
};

export function handoffFromDiagnosis(
  result: DiagnosisResult,
  version: PlanVersion,
): RepairHandoff | null {
  if (!result.active_version_id) return null;
  if (result.project_id !== version.project_id) return null;
  if (result.active_version_id !== version.version_id) return null;
  const partIds = new Set(version.plan.parts.map((part) => part.id));
  const seen = new Set<string>();
  const targetIds: string[] = [];
  for (const id of result.diagnosis.affected_ids) {
    if (!partIds.has(id) || seen.has(id)) continue;
    seen.add(id);
    targetIds.push(id);
  }
  if (targetIds.length === 0) return null;
  return {
    projectId: version.project_id,
    versionId: version.version_id,
    targetIds,
    failureType: result.diagnosis.failure_type,
    source: "muse_diagnosis",
  };
}

export function isHandoffCurrent(
  handoff: RepairHandoff | null | undefined,
  projectId: string,
  versionId: string,
): boolean {
  return (
    handoff != null &&
    handoff.projectId === projectId &&
    handoff.versionId === versionId
  );
}

export function draftFromHandoff(
  handoff: RepairHandoff,
  targetId: string,
): RepairDraftFields {
  return {
    kind: "replace_part",
    targetId,
    stockId: "",
    width: "",
    height: "",
    rationale: `From Muse diagnosis (unverified): ${handoff.failureType}`,
  };
}
