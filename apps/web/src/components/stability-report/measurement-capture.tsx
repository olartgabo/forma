"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { StabilityMeasurementRequest } from "../../lib/generated/api-contracts";
import type { AnalysisContext, ExpectedContext } from "./client";
import {
  confirmations,
  measurementContext,
  measurementsFromForm,
  MeasurementSaveError,
  saveMeasurements,
} from "./measurement-client";

import {
  pendingMeasurements,
  retainMeasurement,
  clearMeasurement,
  type PendingMeasurement,
} from "./measurement-pending";

function NumberField({ name, label }: { name: string; label: string }) {
  return (
    <label style={{ display: "grid", gap: 4 }}>
      {label}
      <input
        name={name}
        inputMode="decimal"
        type="text"
        required
        autoComplete="off"
        style={{ width: "100%", minWidth: 0 }}
      />
    </label>
  );
}
function BodyFields({ prefix, title }: { prefix: string; title: string }) {
  return (
    <fieldset style={{ minWidth: 0 }}>
      <legend>{title}</legend>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
          gap: 12,
        }}
      >
        <NumberField name={`${prefix}_mass_g`} label={`${title} mass (g)`} />
        <NumberField
          name={`${prefix}_mass_resolution_g`}
          label={`${title} mass resolution (g)`}
        />
        {(["x", "y", "z"] as const).map((axis) => (
          <NumberField
            key={axis}
            name={`${prefix}_${axis}_mm`}
            label={`${title} COM ${axis} (mm)`}
          />
        ))}
        <NumberField
          name={`${prefix}_position_resolution_mm`}
          label={`${title} position resolution (mm)`}
        />
      </div>
      <label style={{ display: "grid", marginTop: 12 }}>
        {title} measurement method
        <textarea
          name={`${prefix}_method`}
          required
          maxLength={2000}
          rows={2}
        />
      </label>
      {prefix !== "stand" && (
        <label style={{ display: "grid", marginTop: 12 }}>
          {title} placement description
          <textarea
            name={`${prefix}_pose`}
            required
            maxLength={2000}
            rows={2}
          />
        </label>
      )}
    </fieldset>
  );
}

export default function MeasurementCapture({
  token,
  expected,
  available,
  disabled,
  onSessionChange,
  onInvalidate,
  onSaved,
}: {
  token: string;
  expected: ExpectedContext;
  available: boolean;
  disabled: boolean;
  onSessionChange: (active: boolean) => void;
  onInvalidate: () => void;
  onSaved: (historical?: boolean) => void;
}) {
  const [context, setContext] = useState<AnalysisContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingMeasurement | null>(null);
  const [checkingRecovery, setCheckingRecovery] = useState(true);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [needsReload, setNeedsReload] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    void recover();
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);

  async function recover() {
    setCheckingRecovery(true);
    onSessionChange(true);
    try {
      const records = await pendingMeasurements(token, expected.projectId);
      if (!mounted.current) return;
      setPending(records[0] ?? null);
      setStorageBlocked(false);
      setError(null);
      if (records.length) {
        setContext(null);
        onInvalidate();
      }
      onSessionChange(records.length > 0 || !!context);
    } catch (e) {
      if (mounted.current) {
        setStorageBlocked(true);
        setError(
          e instanceof Error
            ? e.message
            : "Browser recovery storage is unavailable. Saving is blocked.",
        );
      }
    } finally {
      if (mounted.current) setCheckingRecovery(false);
    }
  }
  async function begin() {
    if (pending || checkingRecovery || storageBlocked) return;
    controller.current?.abort();
    const own = new AbortController();
    controller.current = own;
    setBusy(true);
    setError(null);
    onSessionChange(true);
    onInvalidate();
    const timeout = setTimeout(() => own.abort(), 20000);
    try {
      const retained = await pendingMeasurements(token, expected.projectId);
      if (retained.length) {
        if (mounted.current) {
          setPending(retained[0]);
          setContext(null);
        }
        return;
      }
      const current = await measurementContext(token, expected, own.signal);
      if (mounted.current && !own.signal.aborted) {
        setContext(current);
        setNeedsReload(false);
        form.current
          ?.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')
          .forEach((input) => {
            input.checked = false;
          });
      }
    } catch (e) {
      if (mounted.current) {
        setError(
          e instanceof Error
            ? e.message
            : "Could not load measurement context.",
        );
        if (!context) onSessionChange(false);
      }
    } finally {
      clearTimeout(timeout);
      if (mounted.current) setBusy(false);
    }
  }
  async function persist(payload: StabilityMeasurementRequest) {
    const own = new AbortController();
    controller.current = own;
    setBusy(true);
    setError(null);
    onSessionChange(true);
    onInvalidate();
    let retained: PendingMeasurement | null = null;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      // The exact request must survive before the first byte can leave the browser.
      retained = await retainMeasurement(token, expected.projectId, payload);
      if (!mounted.current || own.signal.aborted) return;
      setPending(retained);
      timeout = setTimeout(() => own.abort(), 20000);
      await saveMeasurements(
        token,
        {
          projectId: expected.projectId,
          planVersionId: payload.plan_version_id,
          inventoryRevisionId: payload.expected_inventory_revision_id,
        },
        payload,
        own.signal,
      );
      await clearMeasurement(token, retained);
      const remaining = await pendingMeasurements(token, expected.projectId);
      if (mounted.current) {
        setPending(remaining[0] ?? null);
        setContext(null);
        setNeedsReload(false);
        setStorageBlocked(false);
        onSessionChange(remaining.length > 0);
        onSaved(
          payload.plan_version_id !== expected.planVersionId ||
            payload.expected_inventory_revision_id !==
              expected.inventoryRevisionId,
        );
      }
    } catch (e) {
      let uncertain = !(e instanceof MeasurementSaveError) || e.uncertain;
      let failure = e;
      if (!uncertain && retained) {
        try {
          await clearMeasurement(token, retained);
        } catch (clearError) {
          uncertain = true;
          failure = clearError;
        }
      }
      if (mounted.current) {
        if (uncertain) {
          setPending(retained ?? pending);
          if (!retained) setStorageBlocked(true);
        } else {
          try {
            const remaining = await pendingMeasurements(
              token,
              expected.projectId,
            );
            setPending(remaining[0] ?? null);
            onSessionChange(remaining.length > 0 || !!context);
          } catch (recoveryError) {
            setStorageBlocked(true);
            failure = recoveryError;
          }
        }
        setNeedsReload(!uncertain && !!context);
        setError(
          failure instanceof Error
            ? failure.message
            : "Save outcome unknown. Retry the retained save.",
        );
      }
    } finally {
      if (timeout) clearTimeout(timeout);
      if (mounted.current) setBusy(false);
    }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !context ||
      pending ||
      needsReload ||
      busy ||
      checkingRecovery ||
      storageBlocked
    )
      return;
    try {
      const measurements = measurementsFromForm(
        new FormData(event.currentTarget),
      );
      const payload: StabilityMeasurementRequest = {
        plan_version_id: context.plan_version_id,
        expected_inventory_revision_id: context.inventory_revision_id,
        expected_last_event_id: context.last_event_id,
        idempotency_key: `stability-${crypto.randomUUID()}`,
        user_confirmed: true,
        measurements,
      };
      void persist(payload);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check the measurements.");
    }
  }
  return (
    <section aria-label="Stability measurements">
      <h4>Measured inputs</h4>
      <p>
        Record the assembled stand, including connectors, and both device
        orientations. Blank or unknown values cannot produce a measured
        calculation.
      </p>
      {!context && !pending && (
        <>
          {!available && (
            <p>
              Analyze the current plan first. Record the actual assembly steps
              before entering mechanical measurements.
            </p>
          )}
          <button
            type="button"
            disabled={
              disabled ||
              busy ||
              checkingRecovery ||
              storageBlocked ||
              !available ||
              !token
            }
            onClick={begin}
          >
            {busy
              ? "Loading measurement context…"
              : "Record stability measurements"}
          </button>
        </>
      )}
      {checkingRecovery && (
        <p role="status">Checking retained measurement saves…</p>
      )}
      {error && <p role="alert">{error}</p>}
      {storageBlocked && (
        <button
          type="button"
          disabled={busy || checkingRecovery}
          onClick={recover}
        >
          Check recovery storage again
        </button>
      )}
      {pending && (
        <div role="status" style={{ overflowWrap: "anywhere" }}>
          <p>
            A measurement save is retained on this browser until its outcome is
            resolved. No new measurement can be saved yet. Reloading or leaving
            this plan does not discard this request.
          </p>
          <p>
            Retained plan: {pending.payload.plan_version_id}. Inventory:{" "}
            {pending.payload.expected_inventory_revision_id}.
          </p>
          {(pending.payload.plan_version_id !== expected.planVersionId ||
            pending.payload.expected_inventory_revision_id !==
              expected.inventoryRevisionId) && (
            <p>
              This is an earlier plan or inventory. Retry resolves that
              historical save; it does not make those measurements current.
            </p>
          )}
          <button
            type="button"
            disabled={disabled || busy || checkingRecovery || storageBlocked}
            onClick={() => persist(pending.payload)}
          >
            Retry the same measurement save
          </button>
        </div>
      )}
      {context && (
        <>
          <p>
            Coordinate origin: center of the front base edge on the table. x
            runs across the width, y toward the rear, z upward. Enter center of
            mass (COM) measured by a documented balance method; the geometric
            midpoint is not a measurement.
          </p>
          <p>
            Inputs use grams and millimetres and are saved in kilograms and
            metres. Before sending, the exact request is retained locally in
            this browser until its outcome is confirmed; your owner credential
            is never stored. Reconnect with the same owner to recover it after a
            reload. Resolution describes your measurement instrument; this point
            calculation is not a guaranteed uncertainty bound.
          </p>
          <form ref={form} onSubmit={submit}>
            <fieldset
              disabled={
                disabled ||
                busy ||
                !!pending ||
                needsReload ||
                checkingRecovery ||
                storageBlocked
              }
              style={{
                border: 0,
                padding: 0,
                minWidth: 0,
                display: "grid",
                gap: 16,
              }}
            >
              <BodyFields prefix="stand" title="Complete stand" />
              <BodyFields prefix="portrait" title="Portrait device" />
              <BodyFields prefix="landscape" title="Landscape device" />
              <fieldset style={{ minWidth: 0 }}>
                <legend>Actual supporting contact rectangle</legend>
                <p>
                  This release supports one continuous horizontal rectangle
                  contained within the base. Gaps, rocking and irregular contact
                  need a different model.
                </p>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                    gap: 12,
                  }}
                >
                  <NumberField
                    name="contact_x_min_mm"
                    label="Contact x minimum (mm)"
                  />
                  <NumberField
                    name="contact_x_max_mm"
                    label="Contact x maximum (mm)"
                  />
                  <NumberField
                    name="contact_y_min_mm"
                    label="Contact y minimum (mm)"
                  />
                  <NumberField
                    name="contact_y_max_mm"
                    label="Contact y maximum (mm)"
                  />
                  <NumberField
                    name="contact_resolution_mm"
                    label="Contact resolution (mm)"
                  />
                </div>
                <label style={{ display: "grid", marginTop: 12 }}>
                  Contact measurement method
                  <textarea
                    name="contact_method"
                    required
                    maxLength={2000}
                    rows={2}
                  />
                </label>
              </fieldset>
              <NumberField
                name="required_margin_mm"
                label="Required tipping reserve (mm)"
              />
              <p>
                Choose the reserve you want tested. Zero requests the
                mathematical tipping boundary; it does not establish a safe
                design.
              </p>
              <fieldset style={{ minWidth: 0 }}>
                <legend>Observed measurements and model assumptions</legend>
                {confirmations.map(([name, label]) => (
                  <label
                    key={name}
                    style={{ display: "block", marginBlock: 10 }}
                  >
                    <input type="checkbox" name={name} required /> {label}
                  </label>
                ))}
                <label style={{ display: "block", marginBlock: 10 }}>
                  <input name="user_confirmed" type="checkbox" required /> These
                  are my measurements for this assembly and the described device
                  poses, not example values. Saving them does not record a
                  passed physical test.
                </label>
              </fieldset>
              <button type="submit">Save stability measurements</button>
            </fieldset>
          </form>
          {needsReload && (
            <button type="button" disabled={busy} onClick={begin}>
              Reload measurement context
            </button>
          )}
          {!pending && !busy && !storageBlocked && !checkingRecovery && (
            <button
              type="button"
              onClick={() => {
                setContext(null);
                setError(null);
                setNeedsReload(false);
                onSessionChange(false);
              }}
            >
              Cancel measurement entry
            </button>
          )}
          {busy && <p role="status">Saving or loading measurements…</p>}
        </>
      )}
    </section>
  );
}
