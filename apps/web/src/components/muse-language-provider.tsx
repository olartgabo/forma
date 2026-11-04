"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
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

const LANGUAGE_KEY = "forma-language";

const MuseLanguageContext = createContext<MuseLanguageValue>({
  locale: "en",
  setLocale: () => {},
  copy: museCopyFor("en"),
});

export function useMuseLanguage(): MuseLanguageValue {
  return useContext(MuseLanguageContext);
}

export function MuseLanguageControl() {
  const { locale, setLocale } = useMuseLanguage();
  return (
    <div
      className="workbench-language"
      role="group"
      aria-label={locale === "es" ? "Idioma" : "Language"}
    >
      <button
        type="button"
        lang="en"
        aria-pressed={locale === "en"}
        onClick={() => setLocale("en")}
      >
        English
      </button>
      <button
        type="button"
        lang="es"
        aria-pressed={locale === "es"}
        onClick={() => setLocale("es")}
      >
        Español
      </button>
    </div>
  );
}

export default function MuseLanguageProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [locale, setLocaleState] = useState<MuseLocale>("en");
  useEffect(() => {
    try {
      setLocaleState(
        normalizeMuseLocale(window.localStorage.getItem(LANGUAGE_KEY)),
      );
    } catch {
      // The switch still works for this page when storage is blocked.
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value: MuseLanguageValue = {
    locale,
    setLocale: (next: unknown) => {
      const selected = normalizeMuseLocale(next);
      setLocaleState(selected);
      try {
        window.localStorage.setItem(LANGUAGE_KEY, selected);
      } catch {
        // Keep the active choice even when storage is blocked.
      }
    },
    copy: museCopyFor(locale),
  };
  return (
    <MuseLanguageContext.Provider value={value}>
      {children}
    </MuseLanguageContext.Provider>
  );
}
