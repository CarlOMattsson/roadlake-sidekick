import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
} from "react";
import { useWorkWrite } from "../shared/use-work-write";
import type {
  WorkFilters,
  WorkSavedView,
  WorkTransport,
} from "../transport/transport";
import type { SavedViewsLabels } from "./saved-views-labels";
import {
  filtersToDefinition,
  isArchivedView,
  isSaveBlocked,
  viewNameProblem,
  viewsOfTab,
  type SavedViewTab,
} from "./saved-views";
import { initialSavedViewsState, savedViewsReducer } from "./saved-views-state";

/**
 * The button of one row, found by an id attribute. Rows move after a write, so the button is looked
 * up again rather than kept as a reference.
 */
function buttonFor(
  root: HTMLElement | null,
  attribute: string,
  id: string,
): HTMLButtonElement | undefined {
  const buttons = root?.querySelectorAll<HTMLButtonElement>(
    `button[${attribute}]`,
  );
  return Array.from(buttons ?? []).find(
    (button) => button.getAttribute(attribute) === id,
  );
}

/**
 * The state and writes of the saved views panel. It reads the list when it mounts and drops a read that is no
 * longer the newest or that answers after unmount. Writes wait while a read runs, so a list answer never crosses a
 * write. Focus goes to a control only after the list holding it has been drawn.
 */
export function useSavedViewsPanel({
  tab,
  transport,
  labels: s,
  filters,
}: {
  tab: SavedViewTab;
  transport: WorkTransport;
  labels: SavedViewsLabels;
  filters: WorkFilters;
}) {
  const write = useWorkWrite();
  const panelRef = useRef<HTMLDivElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const renameInput = useRef<HTMLInputElement>(null);
  const undoBox = useRef<HTMLDivElement>(null);
  // Set by a write and run once the list has been drawn again (see the layout effect below).
  const pendingFocus = useRef<(() => void) | undefined>(undefined);
  // The write the user last started, so the WriteNotice retry runs the same action again.
  const lastWrite = useRef<(() => void) | undefined>(undefined);
  // Bumped by every list request; an answer that is not the newest one is stale.
  const ticket = useRef(0);
  const mounted = useRef(true);
  const [state, dispatch] = useReducer(
    savedViewsReducer,
    initialSavedViewsState,
  );
  const { views, listPhase, showArchived, name } = state;

  const { definition, dropped } = filtersToDefinition(tab, filters);
  const blocked = isSaveBlocked(dropped);
  const locked = write.busy || listPhase === "loading";
  const active = (views ?? []).filter((view) => !isArchivedView(view));
  const archivedViews = (views ?? []).filter(isArchivedView);
  const formNote = blocked
    ? s.blockedProject
    : state.nameProblem === "required"
      ? s.nameRequired
      : state.nameProblem === "tooLong"
        ? s.nameTooLong
        : undefined;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Focus goes to a control only after the list holding it has been drawn, never on a timer.
  useLayoutEffect(() => {
    const focus = pendingFocus.current;
    pendingFocus.current = undefined;
    focus?.();
  });

  // Reads the list; the state is already "loading" on mount, and an event handler sets it first (readViews).
  const loadViews = useCallback(
    (includeArchived: boolean) => {
      const current = ++ticket.current;
      // The call sits inside the chain, so a transport without the method is a failed read, not a throw.
      Promise.resolve()
        .then(() => transport.listSavedWorkViews(includeArchived))
        .then(
          (list) => {
            if (current !== ticket.current || !mounted.current) return;
            dispatch({ type: "listLoaded", views: viewsOfTab(list, tab) });
          },
          () => {
            if (current !== ticket.current || !mounted.current) return;
            dispatch({ type: "listFailed" });
          },
        );
    },
    [tab, transport],
  );

  useEffect(() => {
    loadViews(false);
  }, [loadViews]);

  /** Shows the loading state, then reads; for the event handlers that start a read. */
  function readViews(includeArchived: boolean) {
    dispatch({ type: "listLoading" });
    loadViews(includeArchived);
  }

  function changeName(value: string) {
    dispatch({ type: "nameChanged", value });
  }

  function save() {
    const problem = viewNameProblem(name);
    if (problem) {
      dispatch({ type: "nameRefused", problem });
      nameInput.current?.focus();
      return;
    }
    if (blocked) return;
    const title = name.trim();
    const draft = definition;
    lastWrite.current = save;
    void write
      .run(JSON.stringify(["create-view", title, draft]), (key) =>
        transport.createSavedWorkView(title, draft, key),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        dispatch({
          type: "saved",
          view: result.saved_view,
          notice: s.saved(result.saved_view.name),
        });
        pendingFocus.current = () => nameInput.current?.focus();
      });
  }

  function startRename(view: WorkSavedView) {
    dispatch({ type: "renameStarted", view });
    pendingFocus.current = () => renameInput.current?.focus();
  }

  function typeRename(id: string, value: string) {
    dispatch({ type: "renameTyped", id, value });
  }

  function cancelRename(id: string) {
    dispatch({ type: "renameCancelled" });
    pendingFocus.current = () =>
      buttonFor(panelRef.current, "data-edit", id)?.focus();
  }

  function commitRename(view: WorkSavedView, value: string) {
    const problem = viewNameProblem(value);
    if (problem) {
      dispatch({ type: "renameRefused", id: view.id, value, problem });
      renameInput.current?.focus();
      return;
    }
    const title = value.trim();
    if (title === view.name) {
      cancelRename(view.id);
      return;
    }
    lastWrite.current = () => commitRename(view, value);
    void write
      .run(
        JSON.stringify(["rename-view", view.id, view.version, title]),
        (key) =>
          transport.updateSavedWorkView(
            view.id,
            view.version,
            { name: title },
            key,
          ),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        dispatch({
          type: "renamed",
          view: result.saved_view,
          notice: s.renamed(result.saved_view.name),
        });
        pendingFocus.current = () =>
          buttonFor(panelRef.current, "data-edit", view.id)?.focus();
      });
  }

  function archive(view: WorkSavedView) {
    lastWrite.current = () => archive(view);
    void write
      .run(JSON.stringify(["archive-view", view.id, view.version]), (key) =>
        transport.archiveSavedWorkView(view.id, view.version, key),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        dispatch({ type: "archived", view: result.saved_view });
        pendingFocus.current = () =>
          undoBox.current?.querySelector("button")?.focus();
      });
  }

  /** Restores an archived view; it is listed as active again, and its row button takes the focus. */
  function restore(id: string, version: number) {
    lastWrite.current = () => restore(id, version);
    void write
      .run(JSON.stringify(["restore-view", id, version]), (key) =>
        transport.restoreSavedWorkView(id, version, key),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        dispatch({
          type: "restored",
          view: result.saved_view,
          notice: s.restoredView(result.saved_view.name),
        });
        pendingFocus.current = () =>
          buttonFor(panelRef.current, "data-open", id)?.focus();
      });
  }

  function retryWrite() {
    lastWrite.current?.();
  }

  function reload() {
    write.clear();
    readViews(showArchived);
  }

  function toggleArchived(next: boolean) {
    dispatch({ type: "showArchivedSet", value: next });
    readViews(next);
  }

  return {
    state,
    write,
    blocked,
    definition,
    locked,
    active,
    archivedViews,
    formNote,
    panelRef,
    nameInput,
    renameInput,
    undoBox,
    retryWrite,
    readViews,
    changeName,
    save,
    startRename,
    typeRename,
    cancelRename,
    commitRename,
    archive,
    restore,
    reload,
    toggleArchived,
  };
}
