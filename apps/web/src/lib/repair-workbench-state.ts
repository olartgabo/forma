import type { RepairPatch } from "./generated/contracts";
import type {
  AdaptCommitRequest,
  AdaptPreviewSet,
  AdaptSimulateRequest,
} from "./generated/api-contracts";
// prettier-ignore
// @ts-expect-error -- Node type-stripping (tests import .ts directly) requires the explicit .ts extension; tsconfig lacks allowImportingTsExtensions, so TS5097 is expected here.
import { isCandidateSetCurrent, mergeMuseCandidates } from "./repair-candidates.ts";

export const DRAFT_CHANGE_NOTICE =
  "Earlier previews were cleared because the draft changed. Simulate again before approving a repair.";

export type RepairWorkbenchState = {
  candidates: readonly RepairPatch[];
  candidateSetVersion: number;
  previews: AdaptPreviewSet | null;
  previewCandidateSetVersion: number | null;
  choice: string;
  approved: boolean;
  museCandidateIds: ReadonlySet<string>;
  draftChangeNotice: string;
  pendingSimulation: AdaptSimulateRequest | null;
  pendingApproval: AdaptCommitRequest | null;
  museRequestPending: boolean;
  museRequestToken: number;
  museRequestEpoch: number;
  planVersionEpoch: number;
  removedCandidateIds: ReadonlySet<string>;
};

export const initialRepairWorkbenchState: RepairWorkbenchState = {
  candidates: [],
  candidateSetVersion: 0,
  previews: null,
  previewCandidateSetVersion: null,
  choice: "",
  approved: false,
  museCandidateIds: new Set(),
  draftChangeNotice: "",
  pendingSimulation: null,
  pendingApproval: null,
  museRequestPending: false,
  museRequestToken: 0,
  museRequestEpoch: 0,
  planVersionEpoch: 0,
  removedCandidateIds: new Set(),
};

export function createInitialRepairWorkbenchState(): RepairWorkbenchState {
  return {
    ...initialRepairWorkbenchState,
    candidates: [],
    museCandidateIds: new Set(),
    removedCandidateIds: new Set(),
  };
}

export type RepairWorkbenchAction =
  | { type: "addManual"; candidate: RepairPatch }
  | { type: "removeCandidate"; id: string }
  | { type: "museRequested"; token?: number }
  | {
      type: "museResolved";
      candidates: readonly RepairPatch[];
      requestToken?: number;
      epoch?: number;
    }
  | { type: "simulateStarted"; request: AdaptSimulateRequest }
  | {
      type: "simulateResolved";
      previews: AdaptPreviewSet;
      startedVersion: number;
    }
  | { type: "simulateFailed" }
  | { type: "approveStarted"; request: AdaptCommitRequest }
  | { type: "approveResolved" }
  | { type: "approveFailed" }
  | { type: "versionChanged" }
  | { type: "reset" }
  | { type: "previewsCleared" }
  | { type: "remainingStockChanged" }
  | { type: "choiceSelected"; previewId: string }
  | { type: "approvedChanged"; approved: boolean }
  | { type: "draftChangeNoticeCleared" };

function hadPreviews(state: RepairWorkbenchState): boolean {
  return state.previews !== null || state.choice !== "" || state.approved;
}

function clearedPreviews(state: RepairWorkbenchState): RepairWorkbenchState {
  return {
    ...state,
    previews: null,
    previewCandidateSetVersion: null,
    choice: "",
    approved: false,
  };
}

function invalidatedForCandidateChange(
  state: RepairWorkbenchState,
  candidates: readonly RepairPatch[],
  noticeOnHadPreviews: boolean,
): RepairWorkbenchState {
  const had = hadPreviews(state);
  return {
    ...clearedPreviews(state),
    candidates,
    candidateSetVersion: state.candidateSetVersion + 1,
    draftChangeNotice:
      noticeOnHadPreviews && had
        ? DRAFT_CHANGE_NOTICE
        : state.draftChangeNotice,
  };
}

export function repairWorkbenchReducer(
  state: RepairWorkbenchState,
  action: RepairWorkbenchAction,
): RepairWorkbenchState {
  switch (action.type) {
    case "addManual": {
      const removedCandidateIds = new Set(state.removedCandidateIds);
      removedCandidateIds.delete(action.candidate.id);
      return {
        ...invalidatedForCandidateChange(
          state,
          [...state.candidates, action.candidate],
          false,
        ),
        removedCandidateIds,
      };
    }
    case "removeCandidate": {
      if (!state.candidates.some((candidate) => candidate.id === action.id))
        return state;
      return {
        ...invalidatedForCandidateChange(
          state,
          state.candidates.filter((candidate) => candidate.id !== action.id),
          false,
        ),
        removedCandidateIds: new Set([...state.removedCandidateIds, action.id]),
      };
    }
    case "museRequested": {
      const token =
        action.token !== undefined ? action.token : state.museRequestToken + 1;
      return {
        ...state,
        museRequestPending: true,
        museRequestToken: token,
        museRequestEpoch: state.planVersionEpoch,
      };
    }
    case "museResolved": {
      const tokenMatches =
        action.requestToken === undefined ||
        action.requestToken === state.museRequestToken;
      const epochMatches =
        action.epoch === undefined || action.epoch === state.planVersionEpoch;
      if (!tokenMatches || !epochMatches) return state;
      // A request that was pending for a superseded plan version is stale.
      if (
        state.museRequestPending &&
        state.museRequestEpoch !== state.planVersionEpoch
      )
        return state;
      const merged = mergeMuseCandidates(
        state.candidates,
        action.candidates.filter(
          (candidate) => !state.removedCandidateIds.has(candidate.id),
        ),
      );
      if (merged.added === 0) {
        if (!state.museRequestPending) return state;
        return { ...state, museRequestPending: false };
      }
      const next = invalidatedForCandidateChange(state, merged.next, true);
      return {
        ...next,
        museCandidateIds: new Set([
          ...state.museCandidateIds,
          ...merged.addedIds,
        ]),
        museRequestPending: false,
      };
    }
    case "simulateStarted":
      return { ...state, pendingSimulation: action.request };
    case "simulateResolved": {
      if (
        !isCandidateSetCurrent(action.startedVersion, state.candidateSetVersion)
      )
        return { ...state, pendingSimulation: null };
      return {
        ...state,
        pendingSimulation: null,
        previews: action.previews,
        previewCandidateSetVersion: action.startedVersion,
        choice:
          action.previews.previews.find((item) => item.version)?.preview_id ??
          "",
        approved: false,
      };
    }
    case "simulateFailed":
      return { ...state, pendingSimulation: null };
    case "approveStarted":
      return { ...state, pendingApproval: action.request };
    case "approveResolved":
      return { ...state, pendingApproval: null };
    case "approveFailed":
      return { ...state, pendingApproval: null };
    case "versionChanged":
    case "reset":
      return {
        ...state,
        candidates: [],
        candidateSetVersion: state.candidateSetVersion + 1,
        previews: null,
        previewCandidateSetVersion: null,
        choice: "",
        approved: false,
        museCandidateIds: new Set(),
        draftChangeNotice: "",
        pendingSimulation: null,
        pendingApproval: null,
        museRequestPending: false,
        museRequestToken: state.museRequestToken + 1,
        museRequestEpoch: state.planVersionEpoch + 1,
        planVersionEpoch: state.planVersionEpoch + 1,
        removedCandidateIds: new Set(),
      };
    case "previewsCleared": {
      const had = hadPreviews(state);
      return {
        ...clearedPreviews(state),
        draftChangeNotice: had ? DRAFT_CHANGE_NOTICE : state.draftChangeNotice,
      };
    }
    case "remainingStockChanged":
      return {
        ...clearedPreviews(state),
        candidateSetVersion: state.candidateSetVersion + 1,
        pendingSimulation: null,
        draftChangeNotice: hadPreviews(state)
          ? DRAFT_CHANGE_NOTICE
          : state.draftChangeNotice,
      };
    case "choiceSelected":
      return { ...state, choice: action.previewId, approved: false };
    case "approvedChanged":
      return { ...state, approved: action.approved };
    case "draftChangeNoticeCleared":
      return { ...state, draftChangeNotice: "" };
    default:
      return state;
  }
}

export function canApprove(state: RepairWorkbenchState): boolean {
  return (
    state.previews !== null &&
    state.previewCandidateSetVersion !== null &&
    isCandidateSetCurrent(
      state.previewCandidateSetVersion,
      state.candidateSetVersion,
    )
  );
}

export const canApproveRepair = canApprove;
