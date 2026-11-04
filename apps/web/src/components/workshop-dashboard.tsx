"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, listSavedProjects, loadProject } from "../lib/api";
import type {
  Project,
  SavedProjectSummary,
} from "../lib/generated/api-contracts";
import FormaWordmark from "./forma-wordmark";
import WorkshopIllustration, { WorkshopIcon } from "./workshop-illustrations";
import ProjectThumbnail from "./project-thumbnail";
import SourcingPanel from "./sourcing-panel";
import styles from "./workshop-dashboard.module.css";

type Section =
  "Home" | "My projects" | "My materials" | "Shopping list" | "Explore";
type Filter = "all" | "inventory" | "plan" | "active" | "favorites";
const sections: Section[] = [
  "Home",
  "My projects",
  "My materials",
  "Shopping list",
  "Explore",
];
const status = (p: SavedProjectSummary) =>
  p.active_version_id
    ? "Active plan"
    : p.inventory_confirmed
      ? "No active plan"
      : "Confirm inventory";
const message = (e: unknown) =>
  e instanceof ApiError
    ? e.message
    : "Your workshop could not be loaded. Check the connection and try again.";

export default function WorkshopDashboard(props: {
  token: string;
  disabled: boolean;
  onOpen: (id: string) => void;
  onNewProject: (intent?: "idea" | "materials" | "repair") => void;
  onDisconnect: () => void;
  onResume?: () => void;
  resumeLabel?: string;
  favoriteIds?: ReadonlySet<string>;
  onToggleFavorite?: (id: string) => void;
}) {
  // Keying the session also removes previous-owner content before effects run.
  return <WorkshopSession key={props.token} {...props} />;
}

function WorkshopSession({
  token,
  disabled,
  onOpen,
  onNewProject,
  onDisconnect,
  onResume,
  resumeLabel,
  favoriteIds,
  onToggleFavorite,
}: Parameters<typeof WorkshopDashboard>[0]) {
  const [section, setSection] = useState<Section>("Home");
  const [shoppingMounted, setShoppingMounted] = useState(false);
  const [researchLocked, setResearchLocked] = useState(false);
  const workDisabled = disabled || researchLocked;
  const [projects, setProjects] = useState<readonly SavedProjectSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [list, setList] = useState(false);
  const [materialId, setMaterialId] = useState("");
  const [materialProject, setMaterialProject] = useState<Project | null>(null);
  const [materialError, setMaterialError] = useState("");
  const [materialLoading, setMaterialLoading] = useState(false);
  const [materialAttempt, setMaterialAttempt] = useState(0);
  const epoch = useRef(0);
  const moreController = useRef<AbortController | null>(null);
  useEffect(() => {
    const current = ++epoch.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setProjects([]);
    setCursor(null);
    setMore(false);
    void listSavedProjects(token, { limit: 20 }, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || current !== epoch.current) return;
        setProjects(result.projects);
        setCursor(result.next_cursor ?? null);
      })
      .catch((e) => {
        if (!controller.signal.aborted && current === epoch.current)
          setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted && current === epoch.current)
          setLoading(false);
      });
    return () => {
      epoch.current++;
      controller.abort();
      moreController.current?.abort();
    };
  }, [token, attempt]);
  async function loadMore() {
    if (!cursor || loading || more || disabled) return;
    const current = epoch.current;
    const controller = new AbortController();
    moreController.current = controller;
    setMore(true);
    setError("");
    try {
      const result = await listSavedProjects(
        token,
        { limit: 20, cursor },
        controller.signal,
      );
      if (controller.signal.aborted || current !== epoch.current) return;
      setProjects((existing) => {
        const ids = new Set(existing.map((p) => p.id));
        return [...existing, ...result.projects.filter((p) => !ids.has(p.id))];
      });
      setCursor(result.next_cursor ?? null);
    } catch (e) {
      if (!controller.signal.aborted && current === epoch.current)
        setError(message(e));
    } finally {
      if (!controller.signal.aborted && current === epoch.current)
        setMore(false);
    }
  }
  const selectedMaterialId = materialId || projects[0]?.id || "";
  useEffect(() => {
    setMaterialProject(null);
    setMaterialError("");
    if (
      (section !== "My materials" && section !== "Home") ||
      !selectedMaterialId
    ) {
      setMaterialLoading(false);
      return;
    }
    const controller = new AbortController();
    setMaterialLoading(true);
    void loadProject(token, selectedMaterialId, controller.signal)
      .then((p) => {
        if (!controller.signal.aborted) setMaterialProject(p);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setMaterialError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setMaterialLoading(false);
      });
    return () => controller.abort();
  }, [token, section, selectedMaterialId, materialAttempt]);
  const visible = projects.filter(
    (p) =>
      `${p.goal} ${p.id}`.toLowerCase().includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "inventory" && !p.inventory_confirmed) ||
        (filter === "plan" && p.inventory_confirmed && !p.active_version_id) ||
        (filter === "active" && !!p.active_version_id) ||
        (filter === "favorites" && !!favoriteIds?.has(p.id))),
  );
  const newProject = (intent?: "idea" | "materials" | "repair") => {
    if (!workDisabled) onNewProject(intent);
  };
  const open = (id: string) => {
    if (!workDisabled) onOpen(id);
  };
  const navigate = (next: Section) => {
    if (!workDisabled) {
      if (next === "Shopping list") setShoppingMounted(true);
      setSection(next);
    }
  };
  function cards(items: readonly SavedProjectSummary[]) {
    return (
      <div className={`${styles.cards} ${list ? styles.list : ""}`}>
        {items.map((p) => (
          <article
            className={styles.projectCard}
            key={p.id}
            data-blueprint-surface="project-card"
          >
            <div className={styles.thumbnail}>
              {onToggleFavorite && (
                <button
                  className={styles.favorite}
                  disabled={workDisabled}
                  aria-label={`${favoriteIds?.has(p.id) ? "Remove" : "Add"} ${p.goal || p.id} ${favoriteIds?.has(p.id) ? "from" : "to"} favorites`}
                  aria-pressed={!!favoriteIds?.has(p.id)}
                  onClick={() => {
                    if (!disabled) onToggleFavorite(p.id);
                  }}
                >
                  {favoriteIds?.has(p.id) ? "★" : "☆"}
                </button>
              )}
              <ProjectThumbnail token={token} project={p} />
            </div>
            <div className={styles.cardBody}>
              <span className={styles.tag}>{status(p)}</span>
              <h3>{p.goal || "Untitled project"}</h3>
              <p className={styles.projectId}>{p.id}</p>
              <button
                className={styles.paperButton}
                disabled={workDisabled}
                onClick={() => open(p.id)}
              >
                Open project <span aria-hidden="true">↗</span>
              </button>
            </div>
          </article>
        ))}
      </div>
    );
  }
  return (
    <div className={styles.workshop}>
      <aside className={styles.sidebar} data-blueprint-surface="sidebar">
        <div className={styles.brand} aria-label="FORMA">
          <FormaWordmark />
        </div>
        <nav aria-label="Workshop">
          {sections.map((s, i) => (
            <button
              key={s}
              disabled={workDisabled}
              aria-current={section === s ? "page" : undefined}
              onClick={() => navigate(s)}
            >
              <span aria-hidden="true">
                <WorkshopIcon index={i} />
              </span>
              {s}
            </button>
          ))}
        </nav>
        <div className={styles.sidebarFoot}>
          <button
            disabled={workDisabled}
            onClick={() => {
              if (!workDisabled) onDisconnect();
            }}
          >
            ↪ Disconnect
          </button>
        </div>
      </aside>
      <div className={styles.main}>
        <header className={styles.header}>
          <div>
            <h1>{section}</h1>
          </div>
          <button
            className={styles.paperButton}
            disabled={workDisabled}
            onClick={() => newProject()}
          >
            ＋ New project
          </button>
        </header>
        {onResume && (
          <button
            className={styles.moreButton}
            disabled={workDisabled}
            onClick={() => {
              if (!workDisabled) onResume();
            }}
          >
            {resumeLabel || "Return to current work"} ↗
          </button>
        )}
        {workDisabled && (
          <p role="status" className={styles.notice}>
            Finish or reconcile the current action before leaving your work.
          </p>
        )}
        {loading && (
          <div className={styles.empty} role="status">
            <h2>Loading your projects…</h2>
          </div>
        )}
        {error && (
          <div
            className={styles.notice}
            role="alert"
            data-blueprint-surface="error-notice"
          >
            <h2>We couldn’t load your projects</h2>
            <p>{error}</p>
            <button
              disabled={loading || disabled}
              onClick={() =>
                cursor && projects.length
                  ? void loadMore()
                  : setAttempt((a) => a + 1)
              }
            >
              Try again
            </button>
          </div>
        )}
        {!loading && !error && section === "Home" && projects.length > 0 && (
          <div className={styles.populatedHome}>
            <div className={styles.homeProjects}>
              <section
                className={`${styles.hero} ${styles.resumeHero}`}
                data-blueprint-surface="resume-hero"
              >
                <div>
                  <h2>Continue a project.</h2>
                  <h3>{projects[0].goal || "Untitled project"}</h3>
                  <p>{status(projects[0])}</p>
                  <button
                    disabled={workDisabled}
                    className={styles.paperButton}
                    onClick={() => open(projects[0].id)}
                  >
                    Resume a saved project <span aria-hidden="true">↗</span>
                  </button>
                </div>
                <div className={styles.heroArt}>
                  <ProjectThumbnail token={token} project={projects[0]} />
                </div>
              </section>
              <section>
                <div className={styles.sectionHeading}>
                  <h2>On your workbench</h2>
                  <button
                    disabled={workDisabled}
                    onClick={() => navigate("My projects")}
                  >
                    All projects ↗
                  </button>
                </div>
                {cards(projects.slice(0, 4))}
              </section>
              <section className={styles.quickStart}>
                <button
                  disabled={workDisabled}
                  onClick={() => newProject("idea")}
                >
                  Start with an idea ↗
                </button>
                <button
                  disabled={workDisabled}
                  onClick={() => newProject("materials")}
                >
                  Start with materials ↗
                </button>
                <button
                  disabled={workDisabled}
                  onClick={() => newProject("repair")}
                >
                  Fix something ↗
                </button>
              </section>
            </div>
            <aside className={styles.homeRail} aria-label="Workshop overview">
              <section
                className={styles.railPanel}
                data-blueprint-surface="attention"
              >
                <h2>
                  Needs your attention <span aria-hidden="true">✳</span>
                </h2>
                {projects.some((p) => !p.inventory_confirmed) ? (
                  <ul>
                    {projects
                      .filter((p) => !p.inventory_confirmed)
                      .slice(0, 3)
                      .map((p) => (
                        <li key={p.id}>
                          <span className={styles.tag}>Confirm inventory</span>
                          <h3>{p.goal || "Untitled project"}</h3>
                          <button
                            disabled={workDisabled}
                            onClick={() => open(p.id)}
                          >
                            Review project ↗
                          </button>
                        </li>
                      ))}
                  </ul>
                ) : (
                  <p>
                    No inventory confirmations pending in the loaded projects.
                  </p>
                )}
                <small>
                  Measurements and other checks stay inside each project.
                </small>
              </section>
              <section
                className={styles.railPanel}
                data-blueprint-surface="saved-materials"
              >
                <h2>Saved materials</h2>
                <p className={styles.railContext}>
                  Saved stock ·{" "}
                  {projects.find((p) => p.id === selectedMaterialId)?.goal ||
                    selectedMaterialId}
                </p>
                {materialLoading && (
                  <p role="status">Loading project materials…</p>
                )}
                {materialError && (
                  <div role="alert">
                    <p>{materialError}</p>
                    <button onClick={() => setMaterialAttempt((a) => a + 1)}>
                      Retry materials
                    </button>
                  </div>
                )}
                {materialProject &&
                  (materialProject.stocks?.length ? (
                    <ul className={styles.railStock}>
                      {materialProject.stocks.slice(0, 4).map((s) => (
                        <li key={s.id}>
                          <span aria-hidden="true">▱</span>
                          <div>
                            <strong>{s.id}</strong>
                            <small>
                              {s.material.replaceAll("_", " ")} · {s.kind}
                            </small>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No materials saved in this project.</p>
                  ))}
                <small>Review remaining stock inside the project.</small>
                <button
                  disabled={workDisabled}
                  className={styles.paperButton}
                  onClick={() => navigate("My materials")}
                >
                  View materials ↗
                </button>
              </section>
              <section className={styles.railNote}>
                <span aria-hidden="true">◇</span>
                <h3>Make the most of what you have.</h3>
                <p>
                  Review a project’s missing materials before looking for more.
                </p>
                <button
                  disabled={workDisabled}
                  onClick={() => navigate("Shopping list")}
                >
                  Review project needs ↗
                </button>
              </section>
            </aside>
          </div>
        )}
        {!loading && !error && section === "Home" && projects.length === 0 && (
          <>
            <section
              className={styles.hero}
              data-blueprint-surface="welcome-hero"
            >
              <div>
                <h2>Your workshop starts here.</h2>
                <button
                  disabled={workDisabled}
                  className={styles.paperButton}
                  onClick={() => newProject()}
                >
                  ＋ Start your first project <span aria-hidden="true">↗</span>
                </button>
                <small>
                  Start with an idea, spare materials, or something to fix.
                </small>
              </div>
              <div className={styles.heroArt}>
                <WorkshopIllustration variant="hero" />
              </div>
            </section>
            <div className={styles.entryGrid}>
              {(
                [
                  {
                    kind: "idea",
                    title: "I know what I need",
                    text: "Plan a useful build",
                  },
                  {
                    kind: "materials",
                    title: "See what I can make",
                    text: "Start with your materials",
                  },
                  {
                    kind: "repair",
                    title: "Help me fix something",
                    text: "Bring a problem to FORMA",
                  },
                ] as const
              ).map((item) => (
                <button
                  disabled={workDisabled}
                  key={item.kind}
                  className={styles.entry}
                  data-blueprint-surface={`entry-${item.kind}`}
                  onClick={() => newProject(item.kind)}
                >
                  <WorkshopIllustration kind={item.kind} />
                  <h3>{item.title}</h3>
                  <p>
                    {item.text} <span aria-hidden="true">↗</span>
                  </p>
                </button>
              ))}
            </div>
            <section
              className={styles.materialBanner}
              data-blueprint-surface="material-banner"
            >
              <WorkshopIllustration kind="materials" />
              <div>
                <h2>Have spare materials?</h2>
                <p>Give them a purpose. Add them to your first project.</p>
              </div>
              <button
                className={styles.paperButton}
                disabled={workDisabled}
                onClick={() => newProject("materials")}
              >
                Add materials ↗
              </button>
            </section>
          </>
        )}
        {!loading && section === "My projects" && (
          <>
            <div className={styles.catalogTools}>
              <label className={styles.search}>
                <span aria-hidden="true">⌕</span>
                <input
                  aria-label="Search projects"
                  placeholder="Find a project…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <button
                aria-expanded={filtersOpen}
                onClick={() => setFiltersOpen(!filtersOpen)}
              >
                Filters {filter !== "all" ? "•" : "+"}
              </button>
              <div className={styles.viewToggle}>
                <button
                  aria-label="Grid view"
                  aria-pressed={!list}
                  onClick={() => setList(false)}
                >
                  ▦
                </button>
                <button
                  aria-label="List view"
                  aria-pressed={list}
                  onClick={() => setList(true)}
                >
                  ☰
                </button>
              </div>
            </div>
            <div className={styles.catalogLayout}>
              <section className={styles.catalogResults}>
                <p className={styles.subtle}>
                  {visible.length} loaded project
                  {visible.length === 1 ? "" : "s"}
                </p>
                {visible.length
                  ? cards(visible)
                  : !error && (
                      <div className={styles.empty}>
                        <h2>
                          {projects.length
                            ? "No matching projects"
                            : "Make room for your first idea."}
                        </h2>
                        <p>
                          {projects.length
                            ? "Try another search or clear your filters."
                            : "Your saved builds will live here."}
                        </p>
                        <button
                          disabled={workDisabled}
                          className={styles.paperButton}
                          onClick={() =>
                            projects.length
                              ? (setQuery(""), setFilter("all"))
                              : newProject()
                          }
                        >
                          {projects.length
                            ? "Clear search & filters"
                            : "Start a project ↗"}
                        </button>
                      </div>
                    )}
              </section>
              {filtersOpen && (
                <aside
                  className={styles.filters}
                  aria-label="Project filters"
                  data-blueprint-surface="filters"
                >
                  <h2>
                    Filters <span aria-hidden="true">◇ ◇</span>
                  </h2>
                  <fieldset>
                    <legend>Project status</legend>
                    {filter === "favorites" && (
                      <p>Favorites stay for this session.</p>
                    )}
                    {(
                      [
                        ["all", "All projects"],
                        ["inventory", "Confirm inventory"],
                        ["plan", "No active plan"],
                        ["active", "Active plan"],
                        ["favorites", "Favorites"],
                      ] as const
                    ).map(([value, label]) => (
                      <label key={value}>
                        <input
                          type="radio"
                          name="project-status"
                          checked={filter === value}
                          onChange={() => setFilter(value)}
                        />
                        {label}
                      </label>
                    ))}
                  </fieldset>
                  <p>
                    Statuses reflect saved project summaries, not fabrication
                    readiness.
                  </p>
                </aside>
              )}
            </div>
          </>
        )}
        {!loading && section === "My materials" && (
          <section
            className={styles.panel}
            data-blueprint-surface="materials-panel"
          >
            <h2>Materials belong to a project.</h2>
            <p>
              Review saved stock in its original context. There is no shared
              inventory or reservation between projects.
            </p>
            {projects.length > 0 ? (
              <>
                <label className={styles.projectSelect}>
                  Project
                  <select
                    value={selectedMaterialId}
                    onChange={(e) => setMaterialId(e.target.value)}
                  >
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.goal || p.id}
                      </option>
                    ))}
                  </select>
                </label>
                {materialLoading && (
                  <p role="status">Loading project materials…</p>
                )}
                {materialError && (
                  <div role="alert">
                    <p>{materialError}</p>
                    <button onClick={() => setMaterialAttempt((a) => a + 1)}>
                      Retry materials
                    </button>
                  </div>
                )}
                {materialProject && (
                  <>
                    <p className={styles.tag}>
                      {materialProject.inventory_confirmed
                        ? "Saved inventory confirmed"
                        : "Inventory not confirmed"}
                    </p>
                    {materialProject.stocks?.length ? (
                      <ul className={styles.stockList}>
                        {materialProject.stocks.map((s) => (
                          <li key={s.id}>
                            <strong>{s.id}</strong>
                            <span>
                              {s.material.replaceAll("_", " ")} · {s.kind} ·{" "}
                              {s.condition}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No materials are saved in this project.</p>
                    )}
                    <p>
                      Saved stock is not a fresh measurement of what remains
                      after physical work. Open the project to review its
                      material history.
                    </p>
                    <button
                      disabled={workDisabled}
                      className={styles.paperButton}
                      onClick={() => open(materialProject.id)}
                    >
                      Open project materials ↗
                    </button>
                  </>
                )}
              </>
            ) : (
              !error && (
                <button
                  className={styles.paperButton}
                  disabled={workDisabled}
                  onClick={() => newProject("materials")}
                >
                  Start with materials ↗
                </button>
              )
            )}
          </section>
        )}
        {shoppingMounted && (
          <div hidden={section !== "Shopping list"}>
            <SourcingPanel
              token={token}
              projects={projects}
              disabled={disabled}
              onOpen={open}
              onBusyChange={setResearchLocked}
            />
          </div>
        )}
        {!loading && section === "Explore" && (
          <section
            className={styles.panel}
            data-blueprint-surface="explore-panel"
          >
            <WorkshopIllustration kind="idea" />
            <h2>Start with a desktop idea.</h2>
            <p>
              Explore a low-risk tabletop holder or organizer using your own
              materials. Public templates and community builds are not available
              yet. Every proposed design needs its own measurements and checks.
            </p>
            <button
              disabled={workDisabled}
              className={styles.paperButton}
              onClick={() => newProject("idea")}
            >
              Describe your idea ↗
            </button>
          </section>
        )}
        {!loading &&
          cursor &&
          (section === "My projects" || section === "My materials") && (
            <button
              className={styles.moreButton}
              disabled={disabled || more}
              onClick={() => void loadMore()}
            >
              {more ? "Loading more…" : "Load more projects ↓"}
            </button>
          )}
      </div>
    </div>
  );
}
