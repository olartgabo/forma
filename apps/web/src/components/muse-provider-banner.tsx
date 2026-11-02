"use client";

import type { MuseAvailability } from "../lib/muse-provider";
import { useMuseLanguage } from "./muse-language-provider";

export default function MuseProviderBanner({
  availability,
  onRetry,
}: {
  availability: MuseAvailability;
  onRetry: () => void;
}) {
  const { locale, copy } = useMuseLanguage();
  const spanish = locale === "es";
  if (availability.state === "loading") {
    return (
      <p className="help" aria-live="polite" lang={locale}>
        {spanish ? copy.provider.checking : availability.notice}
      </p>
    );
  }
  if (availability.state === "failed") {
    return (
      <div className="notice" role="note" lang={locale}>
        <p>{spanish ? copy.provider.checkFailed : availability.notice}</p>
        <button type="button" className="secondary" onClick={onRetry}>
          {copy.provider.retryCheck}
        </button>
      </div>
    );
  }
  if (!availability.enabled) {
    return (
      <div className="error" role="alert" lang={locale}>
        <p>{copy.provider.notConfiguredTitle}</p>
        <p>{copy.provider.notConfiguredBody}</p>
        <button type="button" className="secondary" onClick={onRetry}>
          {copy.provider.retryCheck}
        </button>
      </div>
    );
  }
  return (
    <p className="notice" aria-live="polite" lang={locale}>
      {spanish
        ? availability.model
          ? copy.provider.configuredWithModel(availability.model)
          : copy.provider.configured
        : availability.notice}
    </p>
  );
}
