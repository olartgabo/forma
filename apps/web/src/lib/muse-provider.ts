export type MuseProviderStatus =
  | { state: "loading" }
  | { state: "loaded"; configured: boolean; model: string | null }
  | { state: "failed" };

export type MuseAvailability = {
  state: MuseProviderStatus["state"];
  enabled: boolean;
  configured: boolean | null;
  model: string | null;
  reason: string | null;
  notice: string | null;
};

export const MUSE_NOT_CONFIGURED_REASON =
  "Muse isn't configured on this server, so Muse actions are unavailable. Ask the project operator to configure Muse, then retry.";

export function museAvailability(status: MuseProviderStatus): MuseAvailability {
  if (status.state === "loading") {
    return {
      state: "loading",
      enabled: true,
      configured: null,
      model: null,
      reason: null,
      notice: "Checking whether Muse is configured on this server…",
    };
  }
  if (status.state === "failed") {
    return {
      state: "failed",
      enabled: true,
      configured: null,
      model: null,
      reason: null,
      notice:
        "Couldn't check whether Muse is configured on this server. Muse actions remain available; if Muse isn't configured, the request will fail.",
    };
  }
  if (!status.configured) {
    return {
      state: "loaded",
      enabled: false,
      configured: false,
      model: null,
      reason: MUSE_NOT_CONFIGURED_REASON,
      notice: MUSE_NOT_CONFIGURED_REASON,
    };
  }
  const model =
    typeof status.model === "string" && status.model.length > 0
      ? status.model
      : null;
  return {
    state: "loaded",
    enabled: true,
    configured: true,
    model,
    reason: null,
    notice: model
      ? `Muse is configured on this server (${model}).`
      : "Muse is configured on this server.",
  };
}
