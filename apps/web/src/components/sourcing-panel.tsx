"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ResearchRequest,
  ResearchRun,
  SavedProjectSummary,
  SourcingNeeds,
  ConfirmedLocation,
  LocationChoice,
} from "../lib/generated/api-contracts";
import {
  loadSourcingNeeds,
  researchSuppliers,
  reconcileResearch,
  SourcingError,
  resolveSourcingLocation,
  reverseSourcingLocation,
  pollResearch,
} from "../lib/sourcing-client";
import {
  confirmLocation,
  requestDeviceLocation,
  type LocationCandidate,
} from "../lib/sourcing-location";
import styles from "./sourcing-panel.module.css";

export default function SourcingPanel({
  token,
  projects,
  disabled,
  onOpen,
  onBusyChange,
}: {
  token: string;
  projects: readonly SavedProjectSummary[];
  disabled: boolean;
  onOpen: (id: string) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [projectId, setProjectId] = useState("");
  const [researchLocked, setResearchLocked] = useState(false);
  return (
    <section className={styles.panel} data-blueprint-surface="shopping-panel">
      <h2>Find materials nearby</h2>
      <p>
        Choose a project to review its needs or research an item you want to
        find.
      </p>
      <label>
        Shopping project
        <select
          value={projectId}
          disabled={disabled || researchLocked}
          onChange={(e) => setProjectId(e.target.value)}
        >
          <option value="">Choose a project</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.goal}
            </option>
          ))}
        </select>
      </label>
      {projectId && (
        <ProjectSourcing
          key={`${token}:${projectId}`}
          token={token}
          projectId={projectId}
          disabled={disabled}
          onOpen={onOpen}
          onBusyChange={onBusyChange}
          onProjectLockChange={setResearchLocked}
        />
      )}
      {!projects.length && (
        <p>Create a project first to keep research linked to your work.</p>
      )}
    </section>
  );
}

function ProjectSourcing({
  token,
  projectId,
  disabled,
  onOpen,
  onBusyChange,
  onProjectLockChange,
}: {
  token: string;
  projectId: string;
  disabled: boolean;
  onOpen: (id: string) => void;
  onBusyChange?: (busy: boolean) => void;
  onProjectLockChange?: (locked: boolean) => void;
}) {
  const [needs, setNeeds] = useState<SourcingNeeds | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [item, setItem] = useState("");
  const [area, setArea] = useState("");
  const [currency, setCurrency] = useState("");
  const [mapConsent, setMapConsent] = useState(false);
  const [metaConsent, setMetaConsent] = useState(false);
  const [manualLocation, setManualLocation] = useState(false);
  const [choices, setChoices] = useState<readonly LocationChoice[]>([]);
  const [candidate, setCandidate] = useState<LocationCandidate | null>(null);
  const [location, setLocation] = useState<ConfirmedLocation | null>(null);
  const [locationBusy, setLocationBusy] = useState(false);
  const [locationMessage, setLocationMessage] = useState("");
  const [attribution, setAttribution] = useState("");
  const [radius, setRadius] = useState(5000);
  const [category, setCategory] = useState<
    "hardware" | "stationery" | "doityourself" | "craft"
  >("hardware");
  const [resultLocation, setResultLocation] =
    useState<ConfirmedLocation | null>(null);
  const locationEpoch = useRef(0);
  const locationController = useRef<AbortController | null>(null);
  const [lookupMode, setLookupMode] = useState<"suppliers" | "supplier_page">(
    "suppliers",
  );
  const [supplierUrl, setSupplierUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [pending, setPending] = useState<ResearchRequest | null>(null);
  useEffect(() => {
    onBusyChange?.(busy || locationBusy);
  }, [onBusyChange, busy, locationBusy]);
  useEffect(() => {
    onProjectLockChange?.(busy || uncertain || locationBusy);
  }, [onProjectLockChange, busy, uncertain, locationBusy]);
  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);
  useEffect(() => () => onProjectLockChange?.(false), [onProjectLockChange]);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const current = new AbortController();
    controller.current = current;
    setNeeds(null);
    setError("");
    void loadSourcingNeeds(token, projectId, current.signal)
      .then((value) => {
        if (!current.signal.aborted) {
          setNeeds(value);
          setUncertain(!!value.pending_run_id);
        }
      })
      .catch((e) => {
        if (!current.signal.aborted)
          setError(
            e instanceof Error ? e.message : "Could not load project needs.",
          );
      });
    return () => {
      current.abort();
      controller.current?.abort();
      locationEpoch.current++;
      locationController.current?.abort();
    };
  }, [token, projectId, refresh]);
  function clearLocation() {
    locationEpoch.current++;
    locationController.current?.abort();
    setLocationBusy(false);
    setLocation(null);
    setCandidate(null);
    setChoices([]);
    setLocationMessage("");
    setAttribution("");
  }
  async function resolveArea() {
    if (
      !mapConsent ||
      !area.trim() ||
      locationBusy ||
      busy ||
      disabled ||
      uncertain
    )
      return;
    clearLocation();
    const epoch = locationEpoch.current;
    const current = new AbortController();
    locationController.current = current;
    setLocationBusy(true);
    try {
      const value = await resolveSourcingLocation(
        token,
        projectId,
        area.trim(),
        mapConsent,
        current.signal,
      );
      if (epoch !== locationEpoch.current || current.signal.aborted) return;
      setChoices(value.choices ?? []);
      setAttribution(value.attribution ?? "");
      setLocationMessage(
        (value.choices ?? []).length
          ? "Choose the intended city, then confirm the search area. Distances will be from its center, not your home."
          : "No matching city was found. Add a country or region and try again.",
      );
    } catch (e) {
      if (epoch === locationEpoch.current && !current.signal.aborted)
        setLocationMessage(
          e instanceof Error
            ? e.message
            : "Could not resolve this city. Enter another city and country.",
        );
    } finally {
      if (epoch === locationEpoch.current) setLocationBusy(false);
    }
  }
  async function locateDevice() {
    if (!mapConsent || locationBusy || busy || disabled || uncertain) return;
    clearLocation();
    const epoch = locationEpoch.current;
    const current = new AbortController();
    locationController.current = current;
    setLocationBusy(true);
    try {
      const value = await requestDeviceLocation(navigator.geolocation);
      if (epoch !== locationEpoch.current) return;
      const confirmed = confirmLocation(value, true, mapConsent);
      setLocation(confirmed);
      setArea(confirmed.label);
      setLocationMessage(
        "Approximate device area selected. Looking up its city and currency…",
      );
      try {
        const resolved = await reverseSourcingLocation(
          token,
          projectId,
          confirmed,
          current.signal,
        );
        if (epoch !== locationEpoch.current || current.signal.aborted) return;
        setLocation(resolved.location);
        setArea(resolved.location.label);
        setCurrency(
          (previous) => previous || resolved.suggested_currency || "",
        );
        setAttribution(resolved.attribution);
        setLocationMessage(
          "Approximate location ready. You can edit the price currency below.",
        );
      } catch {
        if (epoch !== locationEpoch.current || current.signal.aborted) return;
        setManualLocation(true);
        setLocationMessage(
          "Your approximate point is selected, but its city could not be found. Enter a city and country below for Meta price research, or try location again.",
        );
      }
    } catch (e) {
      if (epoch === locationEpoch.current) {
        setManualLocation(true);
        setLocationMessage(
          e instanceof Error ? e.message : "Enter a city and country instead.",
        );
      }
    } finally {
      if (epoch === locationEpoch.current) setLocationBusy(false);
    }
  }
  async function search(replay = false) {
    if (
      !needs ||
      busy ||
      disabled ||
      locationBusy ||
      (!replay &&
        (uncertain ||
          (lookupMode === "suppliers" &&
            (!location || !mapConsent || !metaConsent))))
    )
      return;
    const body: ResearchRequest =
      replay && pending
        ? pending
        : {
            expected_revision_id: needs.revision_id,
            idempotency_key: crypto.randomUUID(),
            item: item.trim(),
            area:
              lookupMode === "suppliers" && location
                ? location.label.slice(0, 120)
                : area.trim(),
            currency,
            provider_transfer_consented:
              lookupMode === "suppliers" && metaConsent,
            source: lookupMode,
            ...(lookupMode === "suppliers" && location
              ? { location, radius_m: radius, category }
              : {}),
            ...(lookupMode === "supplier_page"
              ? { supplier_url: supplierUrl.trim() }
              : {}),
          };
    const current = new AbortController();
    controller.current = current;
    setPending(body);
    setBusy(true);
    setError("");
    let polling = false;
    try {
      const value = await researchSuppliers(
        token,
        projectId,
        body,
        current.signal,
      );
      if (!current.signal.aborted) {
        setRun(value);
        setResultLocation(lookupMode === "suppliers" ? location : null);
        setUncertain(["running", "outcome_unknown"].includes(value.status));
        if (value.status === "running") {
          polling = true;
          await pollResearch(
            token,
            projectId,
            value,
            current.signal,
            (updated) => {
              if (!current.signal.aborted) {
                setRun(updated);
                setUncertain(
                  ["running", "outcome_unknown"].includes(updated.status),
                );
              }
            },
          );
        }
      }
    } catch (e) {
      if (!current.signal.aborted) {
        setError(
          e instanceof Error ? e.message : "Research could not be confirmed.",
        );
        setUncertain(polling || (e instanceof SourcingError && e.uncertain));
      }
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }
  async function reconcile() {
    const runId = run?.id ?? needs?.pending_run_id;
    if (!runId || !needs || busy) return;
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError("");
    try {
      const value = await reconcileResearch(
        token,
        projectId,
        run?.revision_id ?? null,
        runId,
        current.signal,
      );
      if (!current.signal.aborted) {
        setRun(value);
        setUncertain(["running", "outcome_unknown"].includes(value.status));
      }
    } catch (e) {
      if (!current.signal.aborted)
        setError(
          e instanceof Error ? e.message : "Could not check research status.",
        );
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }
  const prompt = `Find ${item || "materials for my project"} near ${area || "my selected area"}. Compare stated prices in ${currency}, quantities, condition and pickup distance. Treat free/zero or DM-for-price listings as price unknown unless clearly a genuine giveaway. Do not contact sellers or purchase anything.`;
  return (
    <div style={{ display: "grid", gap: 16, marginTop: 20, minWidth: 0 }}>
      {!needs && !error && <p role="status">Loading project needs…</p>}
      {error && <p role="alert">{error}</p>}
      {needs && error && (
        <button
          disabled={disabled || busy}
          onClick={() => setRefresh((n) => n + 1)}
        >
          Reload project needs
        </button>
      )}
      {!needs && error && (
        <button disabled={disabled} onClick={() => setRefresh((n) => n + 1)}>
          Reload project needs
        </button>
      )}
      {needs && (
        <>
          <p>
            Project needs reflect the current saved inventory. Research does not
            add materials or approve a build.
          </p>
          {(needs.needs ?? []).length ? (
            <ul>
              {(needs.needs ?? []).map((need) => (
                <li key={need.id}>
                  <button
                    disabled={busy || disabled || uncertain}
                    onClick={() => setItem(need.label)}
                  >
                    {need.label}
                  </button>
                  <p>{need.reason}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p>
              No confirmed material or tool shortfall is recorded. You can
              research a user-requested item below.
            </p>
          )}
          {(needs.guidance ?? []).map((g, i) => (
            <p key={i}>{g}</p>
          ))}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void search();
            }}
            style={{ display: "grid", gap: 12, minWidth: 0 }}
          >
            {lookupMode === "suppliers" && (
              <>
                <section
                  aria-label="Choose your shopping location"
                  style={{
                    border: "1px solid currentColor",
                    padding: 16,
                    borderRadius: 12,
                  }}
                >
                  <h3>Find shops around you</h3>
                  <p>
                    Use your browser location to find nearby suppliers and
                    prices. FORMA rounds coordinates to three decimal places
                    (roughly 100 metres) before sharing them with OpenStreetMap
                    services. Meta receives only your city or region, item
                    request and public business hints for price research.
                  </p>
                  <label
                    style={{ display: "flex", alignItems: "start", gap: 8 }}
                  >
                    <input
                      type="checkbox"
                      checked={mapConsent}
                      disabled={busy || locationBusy || disabled || uncertain}
                      onChange={(e) => {
                        setMapConsent(e.target.checked);
                        if (!e.target.checked) clearLocation();
                      }}
                      style={{ width: "auto" }}
                    />
                    Allow map lookup: share my approximate location or entered
                    city with OpenStreetMap services to identify the area and
                    nearby shops.
                  </label>
                  <button
                    type="button"
                    disabled={
                      !mapConsent ||
                      busy ||
                      locationBusy ||
                      disabled ||
                      uncertain
                    }
                    onClick={() => void locateDevice()}
                  >
                    Use my location
                  </button>
                  <small>
                    Location is requested only when you press this button. Your
                    selection stays in this session; map lookups may be cached
                    for 24 hours.
                  </small>
                </section>
                <details
                  open={manualLocation}
                  onToggle={(e) => setManualLocation(e.currentTarget.open)}
                >
                  <summary>Enter a city instead</summary>
                  <label>
                    City and country
                    <input
                      maxLength={120}
                      value={area}
                      disabled={busy || disabled || uncertain}
                      onChange={(e) => {
                        setArea(e.target.value);
                        clearLocation();
                      }}
                      placeholder="City, country — e.g. San Francisco, United States"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={
                      !mapConsent ||
                      !area.trim() ||
                      busy ||
                      locationBusy ||
                      disabled ||
                      uncertain
                    }
                    onClick={() => void resolveArea()}
                  >
                    Resolve city
                  </button>
                </details>
                {locationBusy && (
                  <p role="status">Finding an approximate search area…</p>
                )}
                {locationMessage && <p role="status">{locationMessage}</p>}
                {choices.length > 0 && (
                  <fieldset
                    disabled={busy || disabled || uncertain}
                    style={{ minWidth: 0 }}
                  >
                    <legend>Choose a city result</legend>
                    {choices.map((choice) => (
                      <label
                        key={choice.id}
                        style={{
                          display: "flex",
                          gap: 8,
                          overflowWrap: "anywhere",
                        }}
                      >
                        <input
                          type="radio"
                          name="sourcing-area"
                          style={{ width: "auto" }}
                          checked={candidate === choice}
                          onChange={() => {
                            setCandidate(choice);
                            setLocation(null);
                          }}
                        />
                        {choice.label}
                      </label>
                    ))}
                  </fieldset>
                )}
                {candidate && candidate.location_basis !== "device" && (
                  <button
                    type="button"
                    disabled={!mapConsent || busy || disabled || uncertain}
                    onClick={() => {
                      setLocation(confirmLocation(candidate, true, mapConsent));
                      setLocationMessage("");
                    }}
                  >
                    Confirm search area
                  </button>
                )}
                {location && (
                  <p role="status">
                    Confirmed: {location.label}.{" "}
                    {location.location_basis === "city_center"
                      ? "City center only; your distance from the center is unknown."
                      : "Approximate device location; distance ranges include reported accuracy and rounding."}
                  </p>
                )}
                {attribution && <small>{attribution}</small>}
                <label>
                  Search radius (km)
                  <input
                    type="number"
                    min="0.1"
                    max="10"
                    step="0.1"
                    required
                    value={radius / 1000}
                    disabled={busy || disabled || uncertain}
                    onChange={(e) => setRadius(Number(e.target.value) * 1000)}
                  />
                </label>
                <label>
                  Shop category
                  <select
                    value={category}
                    disabled={busy || disabled || uncertain}
                    onChange={(e) =>
                      setCategory(e.target.value as typeof category)
                    }
                  >
                    <option value="hardware">Hardware and tools</option>
                    <option value="stationery">Stationery</option>
                    <option value="doityourself">
                      DIY and building supplies
                    </option>
                  </select>
                </label>
                <small>
                  Meta researches prices using your selected area and public
                  business hints. Mapped shops may not publish prices. A nearby
                  shop is not confirmation that this item is in stock.
                </small>
              </>
            )}
            <label>
              Research method
              <select
                value={lookupMode}
                disabled={busy || disabled || uncertain}
                onChange={(e) =>
                  setLookupMode(e.target.value as "suppliers" | "supplier_page")
                }
              >
                <option value="suppliers">
                  Find nearby suppliers and prices
                </option>
                <option value="supplier_page">
                  Advanced: check a supplier page
                </option>
              </select>
            </label>
            {lookupMode === "supplier_page" && (
              <>
                <label>
                  Supplier product URL
                  <input
                    type="url"
                    required
                    maxLength={2000}
                    value={supplierUrl}
                    disabled={busy || disabled || uncertain}
                    onChange={(e) => setSupplierUrl(e.target.value)}
                    placeholder="Paste a product page from a supported store"
                  />
                </label>
                <label>
                  City and country
                  <input
                    required
                    maxLength={120}
                    value={area}
                    disabled={busy || disabled || uncertain}
                    onChange={(e) => setArea(e.target.value)}
                  />
                </label>
                <p>
                  Reads a supported public product page directly; nothing is
                  sent to Meta. A published price does not confirm nearby
                  pickup, stock or delivery charges.
                </p>
              </>
            )}
            <label>
              Item to research
              <input
                maxLength={200}
                required
                value={item}
                disabled={busy || disabled || uncertain}
                onChange={(e) => setItem(e.target.value)}
                placeholder="e.g. scissors"
              />
            </label>
            <small>
              User-requested research; a listing is not available inventory.
              Include the quantity and dimensions you need.
            </small>
            <label>
              Price currency
              <input
                value={currency}
                required
                maxLength={3}
                minLength={3}
                pattern="[A-Z]{3}"
                placeholder="ISO currency code, e.g. USD"
                disabled={busy || disabled || uncertain}
                onChange={(e) =>
                  setCurrency(
                    e.target.value.toUpperCase().replace(/[^A-Z]/g, ""),
                  )
                }
              />
            </label>
            {lookupMode === "suppliers" && (
              <label style={{ display: "flex", alignItems: "start", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={metaConsent}
                  disabled={busy || disabled || uncertain}
                  onChange={(e) => setMetaConsent(e.target.checked)}
                  style={{ width: "auto" }}
                />
                Allow Meta price research: send my item request, coarse city or
                region and public nearby business hints to Meta. Exact or
                approximate coordinates are not sent to Meta.
              </label>
            )}
            <button
              className={styles.paperButton}
              disabled={
                (lookupMode === "suppliers"
                  ? !location ||
                    !mapConsent ||
                    !metaConsent ||
                    radius < 100 ||
                    radius > 10000 ||
                    !Number.isFinite(radius)
                  : !supplierUrl.trim() || !area.trim()) ||
                !item.trim() ||
                !/^[A-Z]{3}$/.test(currency) ||
                locationBusy ||
                busy ||
                disabled ||
                uncertain
              }
              type="submit"
            >
              {busy
                ? "Checking research…"
                : lookupMode === "suppliers"
                  ? "Find nearby suppliers and prices"
                  : "Check supplier page"}
            </button>
          </form>
          {uncertain && (
            <div role="status">
              <p>
                The previous research outcome is unresolved. A new search is
                paused to avoid a duplicate request.
              </p>
              {run || needs.pending_run_id ? (
                <button
                  disabled={busy || disabled}
                  onClick={() => void reconcile()}
                >
                  Check research status
                </button>
              ) : (
                <button
                  disabled={busy || disabled}
                  onClick={() => void search(true)}
                >
                  Recover previous request
                </button>
              )}
            </div>
          )}
          {run && (
            <section aria-label="Supplier research results">
              <h3>
                {run.status === "succeeded"
                  ? "Observed supplier options"
                  : run.status === "no_verified_results"
                    ? "No verified supplier results"
                    : run.status === "failed"
                      ? "Supplier research unavailable"
                      : "Research status pending"}
              </h3>
              <p>
                {run.item} · {run.area} · {run.currency}. Observed{" "}
                {new Date(run.observed_at).toLocaleString()}. Prices and
                availability can change. These results may miss nearby options.
              </p>
              {run.error && <p>{run.error.replaceAll("_", " ")}</p>}
              {run.revision_id !== needs.revision_id && (
                <p>
                  This research belongs to an older inventory snapshot. Review
                  the current project needs before using it.
                </p>
              )}
              {(run.nearby_places ?? []).length > 0 && (
                <section aria-label="Nearby mapped suppliers">
                  <h4>Nearby mapped shops</h4>
                  <p>
                    Mapped businesses, not verified inventory. Distances are
                    straight-line estimates, not travel routes.{" "}
                    {resultLocation?.location_basis === "city_center"
                      ? "The origin is the selected city center, not your device or home."
                      : "The origin is the confirmed approximate search area."}
                  </p>
                  <ul>
                    {(run.nearby_places ?? []).map((place) => (
                      <li key={place.id} style={{ overflowWrap: "anywhere" }}>
                        <a
                          href={place.osm_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            color: "inherit",
                            textDecoration: "underline",
                            fontWeight: 600,
                          }}
                        >
                          {place.name}
                        </a>
                        <p>{place.address || "Address not mapped"}</p>
                        <p>
                          {(place.distance_m / 1000).toFixed(2)} km from the map
                          origin
                          {place.distance_min_m != null &&
                          place.distance_max_m != null
                            ? `; approximately ${(place.distance_min_m / 1000).toFixed(2)}–${(place.distance_max_m / 1000).toFixed(2)} km allowing for location accuracy`
                            : "; city-center distance only, your actual distance is unknown"}
                          .
                        </p>
                        {place.website && (
                          <a
                            href={place.website}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: "inherit",
                              textDecoration: "underline",
                            }}
                          >
                            Shop website ↗
                          </a>
                        )}
                        <p>Branch stock and item price are unverified.</p>
                      </li>
                    ))}
                  </ul>
                  <small>
                    © OpenStreetMap contributors ·{" "}
                    <a
                      href="https://www.openstreetmap.org/copyright"
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "inherit", textDecoration: "underline" }}
                    >
                      Map attribution and license
                    </a>
                  </small>
                </section>
              )}
              {run.discovery_message && <p>{run.discovery_message}</p>}
              <h4>Online published prices</h4>
              <p>
                Store website prices do not establish stock at a nearby branch.
                Confirm pickup availability, package quantity and delivery
                charges.
              </p>
              {!(run.offers ?? []).length && (
                <p>No verified online price was found for this search.</p>
              )}
              <ul>
                {(run.offers ?? []).map((offer, i) => (
                  <li
                    key={`${offer.url}:${i}`}
                    style={{ overflowWrap: "anywhere" }}
                  >
                    <h4>
                      <a
                        href={offer.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          color: "inherit",
                          textDecoration: "underline",
                          fontWeight: 600,
                        }}
                      >
                        {offer.title}
                      </a>
                    </h4>
                    <p>
                      {offer.price === null
                        ? "Price needs confirmation"
                        : `${offer.currency} ${offer.price}`}
                      {offer.price_status !== "listed" &&
                        ` — ${offer.price_status.replaceAll("_", " ")}`}
                    </p>
                    <p>
                      {offer.availability} · {offer.location}
                    </p>
                    <p>{offer.notes}</p>
                    <small>
                      Source: supplier page linked above � Observed{" "}
                      {new Date(run.observed_at).toLocaleString()}. Nearby
                      branch stock remains unknown.
                    </small>
                  </li>
                ))}
              </ul>
              <p>
                Confirm package quantity, condition and all extra charges with
                the supplier. No order has been placed.
              </p>
            </section>
          )}
          <section aria-label="Marketplace handoff">
            <h3>Search Marketplace yourself</h3>
            <p>
              Automatic Marketplace research needs Meta authorization. Open
              Facebook to choose your location and search, or copy this request
              into Meta AI if its shopping features are available to you.
            </p>
            <a
              href="https://www.facebook.com/marketplace/"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: "inherit",
                textDecoration: "underline",
                fontWeight: 600,
              }}
            >
              Open Facebook Marketplace ↗
            </a>
            <label>
              Request for Meta AI
              <textarea
                readOnly
                rows={5}
                value={prompt}
                style={{ width: "100%", maxWidth: "100%" }}
              />
            </label>
            <a
              href="https://www.meta.ai/"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: "inherit",
                textDecoration: "underline",
                fontWeight: 600,
              }}
            >
              Open Meta AI ↗
            </a>
          </section>
          <button
            disabled={disabled || busy || uncertain}
            onClick={() => onOpen(projectId)}
          >
            Review actual materials in project ↗
          </button>
        </>
      )}
    </div>
  );
}
