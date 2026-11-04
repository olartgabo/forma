import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, listSavedProjects } from "../lib/api";
import { workbenchCopy } from "../lib/workbench-language";
import { useMuseLanguage } from "./muse-language-provider";
import StandPreview from "./stand-preview";
import styles from "./workbench-entry.module.css";

export default function WorkbenchEntry({
  onOpen,
}: {
  onOpen: (token: string) => void;
}) {
  const { locale } = useMuseLanguage();
  const copy = workbenchCopy[locale];
  const [credential, setCredential] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<"rejected" | "unavailable" | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = credential.trim();
    if (!token || request.current) return;

    const controller = new AbortController();
    request.current = controller;
    setChecking(true);
    setError(null);
    try {
      await listSavedProjects(
        token,
        { limit: 1 },
        AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
      );
      if (!controller.signal.aborted) onOpen(token);
    } catch (failure) {
      if (controller.signal.aborted) return;
      const rejected =
        failure instanceof ApiError &&
        (failure.status === 401 || failure.status === 403);
      setError(rejected ? "rejected" : "unavailable");
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setChecking(false);
    }
  }

  return (
    <div className={styles.entry}>
      <section className={styles.welcome} aria-labelledby="welcome-title">
        <h1 id="welcome-title">{copy.heading}</h1>
        <p className={styles.lead}>{copy.lead}</p>
        <p className={styles.scope}>{copy.scope}</p>
      </section>
      <section className={styles.access} aria-labelledby="access-title">
        <h2 id="access-title">{copy.accessTitle}</h2>
        <p id="owner-credential-help">{copy.accessHelp}</p>
        <form onSubmit={connect}>
          <label htmlFor="owner-credential">{copy.credential}</label>
          <div className={styles.fields}>
            <input
              id="owner-credential"
              aria-describedby={`owner-credential-help${error ? " owner-credential-error" : ""}`}
              aria-invalid={error === "rejected" || undefined}
              type="password"
              autoComplete="off"
              required
              readOnly={checking}
              value={credential}
              onChange={(event) => {
                setCredential(event.target.value);
                setError(null);
              }}
            />
            <button
              className="primary"
              type="submit"
              disabled={checking || !credential.trim()}
            >
              {copy.open}
              <svg viewBox="0 0 32 28" aria-hidden="true">
                <path d="m4 15 14-2-5-5 3-3 10 8-9 10-3-3 4-4-14 2z" />
                <path d="m25 8 3-5 3 2-4 5zm3 9 4 1-1 3-4-2z" />
              </svg>
            </button>
          </div>
          <p className={styles.feedback} role="status">
            {checking && copy.checking}
          </p>
          {error && (
            <p
              id="owner-credential-error"
              className={styles.error}
              role="alert"
            >
              {copy[error]}
            </p>
          )}
        </form>
      </section>
      <div className={styles.showcase}>
        <StandPreview copy={copy} />
      </div>
    </div>
  );
}
