export interface DiagnosisPlanLoadKey {
  token: string;
  projectId: string;
  activeVersionId: string;
}

export interface DiagnosisPlanLoaderState<Plan> {
  key: DiagnosisPlanLoadKey | null;
  plan: Plan | null;
  error: string;
  loading: boolean;
}

export interface DiagnosisPlanLoader<Plan> {
  getState: () => DiagnosisPlanLoaderState<Plan>;
  subscribe: (listener: () => void) => () => void;
  setKey: (key: DiagnosisPlanLoadKey | null) => void;
  retry: () => void;
  dispose: () => void;
}

function sameKey(
  left: DiagnosisPlanLoadKey,
  right: DiagnosisPlanLoadKey,
): boolean {
  return (
    left.token === right.token &&
    left.projectId === right.projectId &&
    left.activeVersionId === right.activeVersionId
  );
}

export function createDiagnosisPlanLoader<Plan>(options: {
  load: (key: DiagnosisPlanLoadKey, signal: AbortSignal) => Promise<Plan>;
  errorMessage: (error: unknown) => string;
}): DiagnosisPlanLoader<Plan> {
  let state: DiagnosisPlanLoaderState<Plan> = {
    key: null,
    plan: null,
    error: "",
    loading: false,
  };
  let controller: AbortController | null = null;
  let generation = 0;
  const listeners = new Set<() => void>();

  function setState(next: DiagnosisPlanLoaderState<Plan>) {
    state = next;
    for (const listener of listeners) listener();
  }

  function start(key: DiagnosisPlanLoadKey) {
    const currentGeneration = ++generation;
    controller?.abort();
    const loadController = new AbortController();
    controller = loadController;
    setState({ key, plan: null, error: "", loading: true });
    void options
      .load(key, loadController.signal)
      .then((plan) => {
        if (loadController.signal.aborted || currentGeneration !== generation)
          return;
        if (controller === loadController) controller = null;
        setState({ key, plan, error: "", loading: false });
      })
      .catch((failure: unknown) => {
        if (loadController.signal.aborted || currentGeneration !== generation)
          return;
        if (controller === loadController) controller = null;
        setState({
          key,
          plan: null,
          error: options.errorMessage(failure),
          loading: false,
        });
      });
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setKey: (key) => {
      if (key === null) {
        generation += 1;
        controller?.abort();
        controller = null;
        if (
          state.key !== null ||
          state.plan !== null ||
          state.error !== "" ||
          state.loading
        )
          setState({ key: null, plan: null, error: "", loading: false });
        return;
      }
      // Same scope is already loaded, loading or failed: retry is explicit.
      if (state.key !== null && sameKey(state.key, key)) return;
      start(key);
    },
    retry: () => {
      if (state.key === null || state.loading) return;
      start(state.key);
    },
    dispose: () => {
      generation += 1;
      controller?.abort();
      controller = null;
      if (
        state.key !== null ||
        state.plan !== null ||
        state.error !== "" ||
        state.loading
      )
        setState({ key: null, plan: null, error: "", loading: false });
    },
  };
}
