import type { MuseAvailability } from "../lib/muse-provider";

export default function MuseProviderBanner({
  availability,
  onRetry,
}: {
  availability: MuseAvailability;
  onRetry: () => void;
}) {
  if (availability.state === "loading") {
    return (
      <p className="help" aria-live="polite">
        {availability.notice}
      </p>
    );
  }
  if (availability.state === "failed") {
    return (
      <div className="notice" role="note">
        <p>{availability.notice}</p>
        <button type="button" className="secondary" onClick={onRetry}>
          Retry Muse configuration check
        </button>
      </div>
    );
  }
  if (!availability.enabled) {
    return (
      <div className="error" role="alert">
        <p>Muse isn&apos;t configured on this server</p>
        <p>
          Muse actions are unavailable. Ask the project operator to configure
          Muse, then retry.
        </p>
        <button type="button" className="secondary" onClick={onRetry}>
          Retry Muse configuration check
        </button>
      </div>
    );
  }
  return (
    <p className="notice" aria-live="polite">
      {availability.notice}
    </p>
  );
}
