"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import {
  museCopyFor,
  normalizeMuseLocale,
  type MuseCopy,
  type MuseLocale,
} from "../lib/muse-language";

type MuseLanguageValue = {
  locale: MuseLocale;
  setLocale: (locale: unknown) => void;
  copy: MuseCopy;
};

const MuseLanguageContext = createContext<MuseLanguageValue>({
  locale: "en",
  setLocale: () => {},
  copy: museCopyFor("en"),
});

export function useMuseLanguage(): MuseLanguageValue {
  return useContext(MuseLanguageContext);
}

export function MuseLanguageControl() {
  const { locale, setLocale, copy } = useMuseLanguage();
  return (
    <div lang={locale}>
      <p className="help">{copy.language.label}</p>
      <div
        className="muse-actions"
        role="group"
        aria-label={copy.language.label}
      >
        <button
          type="button"
          className="secondary"
          lang="en"
          aria-pressed={locale === "en"}
          onClick={() => setLocale("en")}
        >
          {copy.language.english} · {copy.language.englishName}
        </button>
        <button
          type="button"
          className="secondary"
          lang="es"
          aria-pressed={locale === "es"}
          onClick={() => setLocale("es")}
        >
          {copy.language.spanish} · {copy.language.spanishName}
        </button>
      </div>
      <p className="help">{copy.language.note}</p>
    </div>
  );
}

export default function MuseLanguageProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [locale, setLocaleState] = useState<MuseLocale>("en");
  const value: MuseLanguageValue = {
    locale,
    setLocale: (next: unknown) => setLocaleState(normalizeMuseLocale(next)),
    copy: museCopyFor(locale),
  };
  return (
    <MuseLanguageContext.Provider value={value}>
      <MuseLanguageControl />
      {children}
    </MuseLanguageContext.Provider>
  );
}
