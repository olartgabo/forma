"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { hasModelKey, setModelKey } from "../lib/developer-settings";
const DeveloperContext = createContext(false);
export function DeveloperOnly({ children }: { children: ReactNode }) {
  return useContext(DeveloperContext) ? children : null;
}
export default function DeveloperModeProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [enabled, setEnabled] = useState(false);
  const [key, setKey] = useState("");
  useEffect(() => {
    const clear = () => {
      if (!hasModelKey()) setKey("");
    };
    window.addEventListener("forma-model-key-changed", clear);
    return () => window.removeEventListener("forma-model-key-changed", clear);
  }, []);
  return (
    <DeveloperContext.Provider value={enabled}>
      {children}
      <details style={{ margin: "1rem", maxWidth: "40rem" }}>
        <summary>Settings</summary>
        <label>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => {
              setEnabled(event.target.checked);
              if (!event.target.checked) {
                setKey("");
                setModelKey("");
              }
            }}
          />{" "}
          Developer mode
        </label>
        <p>
          Show technical inputs, complete replies and engine diagnostics.
          Models, guides and required checks remain available in the standard
          view.
        </p>
        {enabled && (
          <section aria-label="Model provider settings">
            <label htmlFor="developer-model-key">
              Your Meta API key (optional)
            </label>
            <input
              id="developer-model-key"
              type="password"
              autoComplete="off"
              value={key}
              maxLength={4096}
              onChange={(event) => {
                setKey(event.target.value);
              }}
            />
            <button type="button" onClick={() => setModelKey(key)}>
              Use this key
            </button>
            <p>
              Uses your key for model requests through this FORMA server. Your
              provider may charge usage. The key stays in memory and clears on
              refresh or when developer mode is turned off. Leave blank to use
              the server provider.
            </p>
            <button
              type="button"
              onClick={() => {
                setKey("");
                setModelKey("");
              }}
            >
              Clear API key
            </button>
          </section>
        )}
      </details>
    </DeveloperContext.Provider>
  );
}
