"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ApiError,
  createProject,
  deletePhoto,
  fetchPhoto,
  listPhotos,
  loadProject,
  saveInventory,
  uploadPhoto,
} from "../lib/api";
import MuseIntakePanel from "./muse-intake-panel";
import MuseDiagnosisPanel from "./muse-diagnosis-panel";
import type {
  BuildRequirements,
  Media,
  Project,
} from "../lib/generated/api-contracts";
import type { Measurement, Stock } from "../lib/generated/contracts";
import BuildRequirementsFields from "./build-requirements-fields";
import DesignReadinessPanel from "./design-readiness-panel";
import PlanWorkbench from "./plan-workbench";
import ProofWorkbench from "./proof-workbench";
import SavedProjectsPanel from "./saved-projects-panel";
import {
  emptyRequirements,
  requirementsError,
} from "../lib/build-requirements";
import type { RepairHandoff } from "../lib/repair-handoff";

type Row = { key: string; stock: Stock; saved: boolean };
type MeasurementField =
  "width_mm" | "height_mm" | "thickness_mm" | "remaining_length_mm";
type Pending =
  | { kind: "create"; key: string; goal: string }
  | {
      kind: "save";
      key: string;
      projectId: string;
      revision: string;
      stocks: readonly Stock[];
      requirements: BuildRequirements;
    }
  | { kind: "upload"; key: string; projectId: string; file: File }
  | { kind: "delete"; key: string; projectId: string; mediaId: string };
const ID_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;
const measurements: { field: MeasurementField; label: string }[] = [
  { field: "width_mm", label: "Width" },
  { field: "height_mm", label: "Height" },
  { field: "thickness_mm", label: "Thickness" },
  { field: "remaining_length_mm", label: "Remaining length" },
];

function unknown(): Measurement {
  return { value: null, unit: "mm", source: "unknown", confirmed: false };
}
function newRow(): Row {
  const id = "stock-" + crypto.randomUUID();
  return {
    key: id,
    saved: false,
    stock: {
      id,
      kind: "sheet",
      material: "cardboard",
      condition: "uncertain",
      width_mm: unknown(),
      height_mm: unknown(),
      thickness_mm: unknown(),
      remaining_length_mm: unknown(),
      usable_regions: [],
      image_ids: [],
    },
  };
}
function rowsFor(project: Project): Row[] {
  return (project.stocks ?? []).map((stock) => ({
    key: stock.id,
    stock,
    saved: true,
  }));
}
function rememberProject(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("project", id);
  else url.searchParams.delete("project");
  window.history.replaceState(null, "", url);
}
function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "The request could not finish. Check the API connection and try again.";
}

function PhotoPreview({
  token,
  projectId,
  photo,
}: {
  token: string;
  projectId: string;
  photo: Media;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setUrl(null);
    setFailed(false);
    void fetchPhoto(token, projectId, photo.id, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, projectId, photo.id, attempt]);
  return (
    <div className="photo-preview">
      {url ? (
        <img src={url} alt={`Inventory photo ${photo.id}`} />
      ) : failed ? (
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          Retry photo preview
        </button>
      ) : (
        <span>Loading photo…</span>
      )}
    </div>
  );
}

export default function IntakeWorkbench() {
  const [credential, setCredential] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [session, setSession] = useState(0);
  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setToken(credential.trim());
    setCredential("");
    setSession((value) => value + 1);
  }
  return (
    <main className="workbench">
      <header className="masthead">
        <a href="/" className="wordmark" aria-label="FORMA home">
          FORMA
          <span className="wordmark-dot" aria-hidden="true" />
        </a>
        <span>Materials into possibilities</span>
      </header>
      {token ? (
        <ProjectWorkbench
          key={session}
          token={token}
          disconnect={() => setToken(null)}
        />
      ) : (
        <div className="welcome-layout">
          <section className="welcome" aria-labelledby="welcome-title">
            <h1 id="welcome-title">Start with what you have.</h1>
            <p className="lead">
              A small stand starts with a clear goal and the materials on your
              desk. Photograph them, measure what you can, and keep the rest
              open.
            </p>
            <ol className="journey">
              <li>
                <strong>Describe the need</strong>
                <span>English or Spanish, in your own words.</span>
              </li>
              <li>
                <strong>Gather your materials</strong>
                <span>One record for each sheet, strip or connector.</span>
              </li>
              <li>
                <strong>Check the measurements</strong>
                <span>Blank values stay unknown.</span>
              </li>
            </ol>
            <p className="scope-note">
              For small, low-risk tabletop fixtures made from reused sheet
              materials. Physical fit and stability need hands-on checks.
            </p>
          </section>
          <section className="access-panel" aria-labelledby="access-title">
            <h2 id="access-title">Open your workbench</h2>
            <p>
              This development preview uses a configured owner credential.
              Hosted sign-in is still being built.
            </p>
            <form onSubmit={connect}>
              <label htmlFor="owner-credential">Owner credential</label>
              <input
                id="owner-credential"
                type="password"
                autoComplete="off"
                required
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
              />
              <button
                className="primary"
                type="submit"
                disabled={!credential.trim()}
              >
                Open workbench
              </button>
            </form>
            <p className="help">
              The credential stays in this tab’s memory. Re-enter it after a
              refresh. Never enter a model-provider API key here.
            </p>
          </section>
        </div>
      )}
    </main>
  );
}

function ProjectWorkbench({
  token,
  disconnect,
}: {
  token: string;
  disconnect: () => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [goal, setGoal] = useState("");
  const [openId, setOpenId] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [requirements, setRequirements] =
    useState<BuildRequirements>(emptyRequirements);
  const [photos, setPhotos] = useState<Media[]>([]);
  const [photoError, setPhotoError] = useState("");
  const [photosLoading, setPhotosLoading] = useState(false);
  const [photoAttempt, setPhotoAttempt] = useState(0);
  const [checked, setChecked] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [planPending, setPlanPending] = useState(false);
  const [pendingRepair, setPendingRepair] = useState<{
    handoff: RepairHandoff;
    targetId: string;
  } | null>(null);
  const [proofRevision, setProofRevision] = useState(0);
  const physicalProgressChanged = useCallback(
    () => setProofRevision((value) => value + 1),
    [],
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [stale, setStale] = useState(false);
  const controller = useRef(new AbortController());
  const epoch = useRef(0);
  const photoEpoch = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const stocks = rows.map((row) => row.stock);
  const dirty =
    project !== null &&
    (JSON.stringify(stocks) !== JSON.stringify(project.stocks ?? []) ||
      JSON.stringify(requirements) !==
        JSON.stringify(project.requirements ?? emptyRequirements()));
  const intakeLocked = busy || pending !== null;
  const locked = intakeLocked || planPending;

  useEffect(() => {
    const lifetime = new AbortController();
    controller.current = lifetime;
    const id = new URL(window.location.href).searchParams.get("project");
    if (id) {
      setOpenId(id);
      if (ID_PATTERN.test(id)) void openProject(id);
      else setError("The project ID in this address is invalid.");
    }
    return () => {
      epoch.current += 1;
      lifetime.abort();
    };
  }, []);

  // A diagnosis handoff is only valid for the project, active version and
  // inventory revision it was created against.
  useEffect(() => {
    setPendingRepair(null);
  }, [project?.id, project?.active_version_id, project?.revision_id]);

  useEffect(() => {
    if (!pendingRepair) return;
    const frame = requestAnimationFrame(() => {
      const region = document.getElementById("repair-review");
      region?.scrollIntoView({ block: "start" });
      region?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [pendingRepair]);

  useEffect(() => {
    if (!project) return;
    const loadController = new AbortController();
    const listEpoch = photoEpoch.current;
    setPhotoError("");
    setPhotosLoading(true);
    void listPhotos(token, project.id, loadController.signal)
      .then((result) => {
        if (!loadController.signal.aborted && listEpoch === photoEpoch.current)
          setPhotos([...result.media]);
      })
      .catch((failure: unknown) => {
        if (!loadController.signal.aborted && listEpoch === photoEpoch.current)
          setPhotoError(errorMessage(failure));
      })
      .finally(() => {
        if (!loadController.signal.aborted && listEpoch === photoEpoch.current)
          setPhotosLoading(false);
      });
    return () => loadController.abort();
  }, [token, project?.id, photoAttempt]);

  function install(next: Project) {
    setProject(next);
    setRows(rowsFor(next));
    setRequirements(next.requirements ?? emptyRequirements());
    setChecked(false);
    setStale(false);
    setOpenId(next.id);
    rememberProject(next.id);
  }
  async function openProject(id: string) {
    if (locked) return;
    if (
      dirty &&
      !window.confirm(
        "Reload this project and discard unsaved materials and requirements?",
      )
    )
      return;
    const requestEpoch = ++epoch.current;
    const signal = controller.current.signal;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await loadProject(token, id, signal);
      if (signal.aborted || requestEpoch !== epoch.current) return;
      setPhotos([]);
      install(next);
      setPhotoAttempt((value) => value + 1);
    } catch (failure) {
      if (!signal.aborted && requestEpoch === epoch.current)
        setError(errorMessage(failure));
    } finally {
      if (!signal.aborted && requestEpoch === epoch.current) setBusy(false);
    }
  }
  async function execute(request: Pending) {
    if (busy || planPending) return;
    const requestEpoch = epoch.current;
    const signal = controller.current.signal;
    const changesPhotos =
      request.kind === "upload" || request.kind === "delete";
    if (changesPhotos) photoEpoch.current += 1;
    setPending(request);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (request.kind === "create") {
        const result = await createProject(
          token,
          request.goal,
          request.key,
          signal,
        );
        if (signal.aborted || requestEpoch !== epoch.current) return;
        setPhotos([]);
        install(result.project);
        setNotice("Project saved. Add the materials you actually have.");
      } else if (request.kind === "save") {
        const result = await saveInventory(
          token,
          request.projectId,
          request.stocks,
          request.revision,
          request.key,
          signal,
          request.requirements,
        );
        if (signal.aborted || requestEpoch !== epoch.current) return;
        install(result.project);
        setNotice(
          "Materials and build requirements saved. Unknown measurements remain open.",
        );
      } else if (request.kind === "upload") {
        const result = await uploadPhoto(
          token,
          request.projectId,
          request.file,
          request.key,
          signal,
        );
        if (signal.aborted || requestEpoch !== epoch.current) return;
        setPhotos((current) =>
          current.some((item) => item.id === result.media.id)
            ? current
            : [...current, result.media],
        );
        if (fileInput.current) fileInput.current.value = "";
        setNotice(
          "Photo saved privately. Link it to the matching material below.",
        );
      } else {
        await deletePhoto(
          token,
          request.projectId,
          request.mediaId,
          request.key,
          signal,
        );
        if (signal.aborted || requestEpoch !== epoch.current) return;
        setPhotos((current) =>
          current.filter((item) => item.id !== request.mediaId),
        );
        setRows((current) =>
          current.map((row) => ({
            ...row,
            stock: {
              ...row.stock,
              image_ids: row.stock.image_ids?.filter(
                (id) => id !== request.mediaId,
              ),
            },
          })),
        );
        setNotice("Photo deleted from this project.");
      }
      setPending(null);
    } catch (failure) {
      if (signal.aborted || requestEpoch !== epoch.current) return;
      setError(errorMessage(failure));
      if (
        failure instanceof ApiError &&
        failure.status >= 400 &&
        failure.status < 500
      ) {
        setPending(null);
        if (request.kind === "save" && failure.status === 409) setStale(true);
      }
    } finally {
      if (!signal.aborted && requestEpoch === epoch.current) {
        setBusy(false);
        if (changesPhotos) {
          photoEpoch.current += 1;
          setPhotoAttempt((value) => value + 1);
        }
      }
    }
  }
  function changeStock(key: string, patch: Partial<Stock>) {
    setRows((current) =>
      current.map((row) =>
        row.key === key ? { ...row, stock: { ...row.stock, ...patch } } : row,
      ),
    );
    setChecked(false);
    setNotice("");
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || locked || !checked) return;
    const confirmedRequirements: BuildRequirements = {
      ...requirements,
      tools: (requirements.tools ?? [])
        .map((tool) => tool.trim())
        .filter(Boolean),
      device_description: requirements.device_description?.trim() || null,
    };
    const requirementError = requirementsError(confirmedRequirements);
    if (requirementError) {
      setError(requirementError);
      return;
    }
    if (stocks.some((stock) => !ID_PATTERN.test(stock.id))) {
      setError(
        "Item IDs must start with a letter and use up to 96 letters, numbers, underscores or hyphens.",
      );
      return;
    }
    if (new Set(stocks.map((stock) => stock.id)).size !== stocks.length) {
      setError("Give each physical item a different ID.");
      return;
    }
    for (const stock of stocks)
      for (const { field, label } of measurements) {
        const value = stock[field].value;
        if (
          value !== null &&
          (!Number.isFinite(value) ||
            (field === "remaining_length_mm" ? value < 0 : value <= 0))
        ) {
          setError(
            `${label} must be ${field === "remaining_length_mm" ? "zero or greater" : "greater than zero"} in millimeters, or left blank.`,
          );
          return;
        }
      }
    void execute({
      kind: "save",
      key: crypto.randomUUID(),
      projectId: project.id,
      revision: project.revision_id,
      stocks: structuredClone(stocks),
      requirements: structuredClone(confirmedRequirements),
    });
  }
  function leave() {
    if (
      (dirty || pending || planPending) &&
      !window.confirm(
        "Disconnect and discard unsaved changes? An unfinished request may already have reached the server; reopen the project to check it.",
      )
    )
      return;
    disconnect();
  }
  return (
    <>
      <div className="session-bar">
        <p>Private development workbench</p>
        <button type="button" className="quiet" onClick={leave}>
          Disconnect
        </button>
      </div>
      <div className="status-area" aria-live="polite" aria-atomic="true">
        {notice && <p className="notice">{notice}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {busy && <p className="help">Saving or loading your project…</p>}
      </div>
      {pending && !busy && (
        <aside className="retry-panel">
          <h2>Confirm the unfinished request</h2>
          <p>
            The connection ended before the result was known. Retry this same
            request to check its outcome without creating a duplicate.
          </p>
          <button
            type="button"
            className="primary"
            onClick={() => void execute(pending)}
          >
            Retry request
          </button>
        </aside>
      )}
      {!project ? (
        <div className="start-layout">
          <section aria-labelledby="goal-title">
            <h1 id="goal-title">What would make your desk work better?</h1>
            <p className="lead">
              Start with a small tabletop stand. Describe what it should hold
              and what you need it to do.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!locked && goal.trim())
                  void execute({
                    kind: "create",
                    key: crypto.randomUUID(),
                    goal: goal.trim(),
                  });
              }}
            >
              <fieldset disabled={locked}>
                <label htmlFor="goal">Your goal, in English or Spanish</label>
                <textarea
                  id="goal"
                  rows={5}
                  maxLength={2000}
                  required
                  value={goal}
                  onChange={(event) => setGoal(event.target.value)}
                />
                <p className="help">
                  Include the object, the space available and what you want to
                  improve. Exact measurements come next.
                </p>
                <button
                  className="primary"
                  type="submit"
                  disabled={!goal.trim()}
                >
                  Create project
                </button>
              </fieldset>
            </form>
          </section>
          <section className="reopen-panel" aria-labelledby="reopen-title">
            <h2 id="reopen-title">Continue a project</h2>
            <p>Use its saved project ID with the same owner credential.</p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void openProject(openId.trim());
              }}
            >
              <fieldset disabled={locked}>
                <label htmlFor="open-project">Project ID</label>
                <input
                  id="open-project"
                  required
                  pattern={"[A-Za-z][A-Za-z0-9_\\-]{0,95}"}
                  value={openId}
                  onChange={(event) => setOpenId(event.target.value)}
                />
                <button type="submit" className="secondary">
                  Open project
                </button>
              </fieldset>
            </form>
            <SavedProjectsPanel
              token={token}
              disabled={locked}
              onOpen={(id) => void openProject(id)}
            />
          </section>
        </div>
      ) : (
        <>
          <section className="project-heading" aria-labelledby="project-title">
            <div>
              <p className="project-id">
                Project ID <span>{project.id}</span>
              </p>
              <h1 id="project-title">{project.goal}</h1>
              <p>
                Save this page’s address to return. Your credential is never
                included.
              </p>
            </div>
            <button
              type="button"
              className="quiet"
              disabled={locked}
              onClick={() => {
                if (
                  dirty &&
                  !window.confirm(
                    "Start another project and discard unsaved materials and requirements?",
                  )
                )
                  return;
                epoch.current += 1;
                setProject(null);
                setRows([]);
                setRequirements(emptyRequirements());
                setPhotos([]);
                setError("");
                setNotice("");
                setStale(false);
                setChecked(false);
                rememberProject(null);
              }}
            >
              Start another project
            </button>
          </section>
          <div className="inventory-layout">
            <section className="photos-panel" aria-labelledby="photos-title">
              <div className="section-title">
                <span aria-hidden="true">1</span>
                <h2 id="photos-title">Photograph your materials</h2>
              </div>
              <p>
                Keep sheets, strips and connectors visible. Photos stay private
                in this project unless you explicitly ask Muse about one below.
              </p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const file = fileInput.current?.files?.[0];
                  if (file && !locked)
                    void execute({
                      kind: "upload",
                      key: crypto.randomUUID(),
                      projectId: project.id,
                      file,
                    });
                }}
              >
                <fieldset disabled={locked}>
                  <label htmlFor="photo-upload">Add a photo</label>
                  <input
                    ref={fileInput}
                    id="photo-upload"
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    required
                  />
                  <p className="help">
                    JPEG, PNG or WebP, up to 8 MiB. A photo cannot establish
                    exact dimensions.
                  </p>
                  <button type="submit" className="secondary">
                    Upload photo
                  </button>
                </fieldset>
              </form>
              {photoError && (
                <div className="error" role="alert">
                  <p>{photoError}</p>
                  <button
                    type="button"
                    onClick={() => setPhotoAttempt((value) => value + 1)}
                  >
                    Reload photos
                  </button>
                </div>
              )}
              {photos.length === 0 ? (
                <p className="empty-note">
                  {photosLoading
                    ? "Loading your private photos…"
                    : "No photos loaded. You can still enter materials by hand."}
                </p>
              ) : (
                <div className="photo-gallery">
                  {photos.map((photo, index) => {
                    const linked = rows.some((row) =>
                      row.stock.image_ids?.includes(photo.id),
                    );
                    const savedLink = project.stocks?.some((stock) =>
                      stock.image_ids?.includes(photo.id),
                    );
                    return (
                      <figure key={photo.id}>
                        <PhotoPreview
                          token={token}
                          projectId={project.id}
                          photo={photo}
                        />
                        <figcaption>
                          Photo {index + 1}
                          <span>
                            {photo.width_px} × {photo.height_px} pixels
                          </span>
                        </figcaption>
                        <button
                          type="button"
                          className="quiet danger"
                          disabled={locked || linked || savedLink}
                          onClick={() => {
                            if (
                              window.confirm(
                                "Delete this private photo from the project?",
                              )
                            )
                              void execute({
                                kind: "delete",
                                key: crypto.randomUUID(),
                                projectId: project.id,
                                mediaId: photo.id,
                              });
                          }}
                        >
                          Delete photo {index + 1}
                        </button>
                        {(linked || savedLink) && (
                          <p className="help">
                            Unlink from materials and save before deleting.
                          </p>
                        )}
                      </figure>
                    );
                  })}
                </div>
              )}
            </section>
            <section
              className="materials-panel"
              aria-labelledby="materials-title"
            >
              <div className="section-title">
                <span aria-hidden="true">2</span>
                <h2 id="materials-title">Record what you have</h2>
              </div>
              <p>
                Use one record per physical item. Measure in millimeters; leave
                a value blank when it is unknown.
              </p>
              <form onSubmit={save}>
                <fieldset
                  disabled={locked || Boolean(project.active_version_id)}
                >
                  {rows.length === 0 && (
                    <div className="empty-note">
                      <h3>Your materials start here</h3>
                      <p>
                        Add a sheet, strip, roll of tape or length of cord. No
                        sizes are assumed.
                      </p>
                    </div>
                  )}
                  {rows.map((row, index) => {
                    const stock = row.stock;
                    const hasRegions = Boolean(stock.usable_regions?.length);
                    const relevant = measurements.filter(({ field }) =>
                      stock.kind === "tape" || stock.kind === "cord"
                        ? field === "remaining_length_mm"
                        : field !== "remaining_length_mm",
                    );
                    return (
                      <article className="stock-record" key={row.key}>
                        <div className="stock-heading">
                          <h3>Material {index + 1}</h3>
                          <button
                            className="quiet danger"
                            type="button"
                            onClick={() => {
                              setRows((current) =>
                                current.filter((item) => item.key !== row.key),
                              );
                              setChecked(false);
                              setNotice("");
                            }}
                          >
                            Remove material {index + 1}
                          </button>
                        </div>
                        <div className="stock-properties">
                          <div>
                            <label htmlFor={`${row.key}-id`}>Item ID</label>
                            <input
                              id={`${row.key}-id`}
                              value={stock.id}
                              readOnly={row.saved}
                              required
                              maxLength={96}
                              pattern={"[A-Za-z][A-Za-z0-9_\\-]{0,95}"}
                              onChange={(event) =>
                                changeStock(row.key, { id: event.target.value })
                              }
                            />
                            <p className="help">
                              Label the physical item with this ID.
                              {row.saved
                                ? " Saved IDs stay fixed."
                                : " Letters, numbers, hyphens or underscores."}
                            </p>
                          </div>
                          <div>
                            <label htmlFor={`${row.key}-kind`}>Item type</label>
                            <select
                              id={`${row.key}-kind`}
                              value={stock.kind}
                              disabled={hasRegions}
                              onChange={(event) =>
                                changeStock(row.key, {
                                  kind: event.target.value as Stock["kind"],
                                })
                              }
                            >
                              <option value="sheet">Sheet</option>
                              <option value="strip">Strip</option>
                              <option value="tape">Tape</option>
                              <option value="cord">Cord</option>
                            </select>
                          </div>
                          <div>
                            <label htmlFor={`${row.key}-material`}>
                              Material
                            </label>
                            <select
                              id={`${row.key}-material`}
                              value={stock.material}
                              disabled={hasRegions}
                              onChange={(event) =>
                                changeStock(row.key, {
                                  material: event.target
                                    .value as Stock["material"],
                                })
                              }
                            >
                              <option value="cardboard">Cardboard</option>
                              <option value="paperboard">Paperboard</option>
                              <option value="other_supported">
                                Other material (requires review)
                              </option>
                            </select>
                          </div>
                          <div>
                            <label htmlFor={`${row.key}-condition`}>
                              Condition
                            </label>
                            <select
                              id={`${row.key}-condition`}
                              value={stock.condition}
                              onChange={(event) =>
                                changeStock(row.key, {
                                  condition: event.target
                                    .value as Stock["condition"],
                                })
                              }
                            >
                              <option value="uncertain">Not checked</option>
                              <option value="usable">Usable</option>
                              <option value="damaged">Damaged</option>
                            </select>
                          </div>
                        </div>
                        <div className="measurements">
                          {relevant.map(({ field, label }) => {
                            const measurement = stock[field];
                            return (
                              <div className="measurement" key={field}>
                                <label htmlFor={`${row.key}-${field}`}>
                                  {label} <span>(mm)</span>
                                </label>
                                <input
                                  id={`${row.key}-${field}`}
                                  type="number"
                                  inputMode="decimal"
                                  step="any"
                                  min="0"
                                  disabled={hasRegions}
                                  value={measurement.value ?? ""}
                                  onChange={(event) => {
                                    const value =
                                      event.target.value === ""
                                        ? null
                                        : Number(event.target.value);
                                    changeStock(row.key, {
                                      [field]:
                                        value === null
                                          ? unknown()
                                          : {
                                              value,
                                              unit: "mm",
                                              source: "user_ruler",
                                              confirmed: false,
                                            },
                                    });
                                  }}
                                />
                                <label
                                  className="checkbox-label"
                                  htmlFor={`${row.key}-${field}-confirmed`}
                                >
                                  <input
                                    id={`${row.key}-${field}-confirmed`}
                                    type="checkbox"
                                    aria-label={`${label} measured and checked`}
                                    disabled={
                                      measurement.value === null || hasRegions
                                    }
                                    checked={measurement.confirmed}
                                    onChange={(event) =>
                                      changeStock(row.key, {
                                        [field]: {
                                          ...measurement,
                                          confirmed: event.target.checked,
                                        },
                                      })
                                    }
                                  />
                                  Measured and checked
                                </label>
                                {measurement.value === null && (
                                  <span className="unknown-note">Unknown</span>
                                )}
                                {measurement.value !== null &&
                                  !measurement.confirmed && (
                                    <span className="unknown-note">
                                      Needs confirmation
                                    </span>
                                  )}
                              </div>
                            );
                          })}
                        </div>
                        {hasRegions && (
                          <p className="help">
                            Existing usable-region geometry is retained.
                            Dimension changes need a separate revision workflow.
                          </p>
                        )}
                        {photos.length > 0 && (
                          <fieldset className="photo-links">
                            <legend>Matching photos</legend>
                            {photos.map((photo, photoIndex) => (
                              <label className="checkbox-label" key={photo.id}>
                                <input
                                  type="checkbox"
                                  checked={
                                    stock.image_ids?.includes(photo.id) ?? false
                                  }
                                  onChange={(event) =>
                                    changeStock(row.key, {
                                      image_ids: event.target.checked
                                        ? [...(stock.image_ids ?? []), photo.id]
                                        : stock.image_ids?.filter(
                                            (id) => id !== photo.id,
                                          ),
                                    })
                                  }
                                />
                                Photo {photoIndex + 1}
                              </label>
                            ))}
                          </fieldset>
                        )}
                      </article>
                    );
                  })}
                  <button
                    type="button"
                    className="secondary add-material"
                    disabled={rows.length >= 32}
                    onClick={() => {
                      setRows((current) => [...current, newRow()]);
                      setChecked(false);
                      setNotice("");
                    }}
                  >
                    Add a material
                  </button>
                  {rows.length >= 32 && (
                    <p className="help">
                      This project supports up to 32 material records.
                    </p>
                  )}
                  <BuildRequirementsFields
                    value={requirements}
                    onChange={(next) => {
                      setRequirements(next);
                      setChecked(false);
                      setNotice("");
                    }}
                  />
                  <div className="save-inventory">
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) => setChecked(event.target.checked)}
                      />
                      I checked these materials, tools and requirements. Blank
                      measurements are still unknown.
                    </label>
                    <div className="save-row">
                      <button
                        type="submit"
                        className="primary"
                        disabled={!checked || rows.length === 0 || stale}
                      >
                        Save materials and requirements
                      </button>
                      <span className="help">
                        {dirty
                          ? "Unsaved changes"
                          : project.inventory_confirmed
                            ? "Inventory saved"
                            : "Inventory not confirmed"}
                      </span>
                    </div>
                  </div>
                </fieldset>
              </form>
              {project.active_version_id && (
                <p className="error">
                  This project already has an active plan. Inventory edits
                  require a plan revision.
                </p>
              )}
              {stale && (
                <aside className="retry-panel">
                  <h3>The saved materials or requirements changed</h3>
                  <p>
                    Reload the latest materials and requirements before saving
                    again. Reloading replaces your unsaved edits.
                  </p>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => void openProject(project.id)}
                  >
                    Reload latest materials and requirements
                  </button>
                </aside>
              )}
            </section>
          </div>
          <MuseIntakePanel
            token={token}
            project={project}
            photos={photos}
            inventoryStale={stale || dirty}
            disabled={locked}
          />
          <MuseDiagnosisPanel
            token={token}
            project={project}
            photos={photos}
            inventoryStale={stale || dirty}
            disabled={locked}
            onRepairHandoff={(handoff, targetId) =>
              setPendingRepair({ handoff, targetId })
            }
          />
          <DesignReadinessPanel
            token={token}
            project={project}
            inventoryStale={stale || dirty}
          />
          <PlanWorkbench
            key={project.id}
            token={token}
            project={project}
            approvalDisabled={intakeLocked || dirty}
            onLockChange={setPlanPending}
            onActivated={(next) => {
              install(next);
              setNotice(
                "Plan approved. Review its instructions and required checks before building.",
              );
            }}
            onReload={() => void openProject(project.id)}
            photos={photos}
            onProgressChange={physicalProgressChanged}
            repairHandoff={pendingRepair}
          />
          <ProofWorkbench
            key={`proof-${project.id}`}
            token={token}
            project={project}
            revision={proofRevision}
            disabled={locked}
          />
          <aside className="next-step-note">
            <h2>What comes next</h2>
            <p>
              Asking Muse returns a read-only observation; it does not change
              your saved materials. Saved plan previews can be reviewed above,
              and active plans support explicit physical reports. Repair
              activation is still being connected. Saving inventory records
              materials and requirements; it does not validate a design or
              authorize a cut.
            </p>
          </aside>
        </>
      )}
    </>
  );
}
