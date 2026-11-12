import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { onEnterKey, preventSubmit } from "../mcp-apps/ui/enter-key";
import { ArchivedRows, UndoLine, WriteNotice } from "./manage-controls";
import type { ManageLabels } from "./manage-labels";
import type { SavedViewsLabels } from "./saved-views-labels";
import {
  filtersToDefinition,
  isArchivedView,
  isSaveBlocked,
  upsertView,
  viewNameProblem,
  viewsOfTab,
  type SavedViewTab,
  type ViewNameProblem,
} from "./saved-views";
import type {
  WorkFilters,
  WorkSavedView,
  WorkSavedViewDefinition,
  WorkTransport,
} from "./transport";
import { useWorkWrite } from "./use-work-write";
import "./saved-views.css";

export type SavedViewsBarProps = {
  /** The tab the bar belongs to; only views saved for this tab are listed. */
  tab: SavedViewTab;
  transport: WorkTransport;
  labels: SavedViewsLabels;
  /** The shared list words for the same locale, e.g. manageLabelsFor(t.dateLocale). */
  manage: ManageLabels;
  /** The filters the tab shows now; "Spara nuvarande vy" saves them. */
  filters: WorkFilters;
  /**
   * Opens a saved view in the tab. Resolves true when the tab shows the view, false when the read
   * failed (the tab keeps its view then).
   */
  onOpen: (
    definition: WorkSavedViewDefinition,
    name: string,
  ) => Promise<boolean>;
};

type OpenStatus =
  | { kind: "opening" }
  | { kind: "opened"; name: string }
  | { kind: "failed"; view: WorkSavedView };

/**
 * The saved views of one Work tab: a visible "Sparade vyer" button that unfolds a panel. The panel
 * reads the list only when it opens, and holds the save form, the list of this tab's views (open,
 * rename, archive) and the archived ones (restore). Opening a view is reported back through onOpen;
 * the open status line stays visible even when the panel is closed.
 */
export function SavedViewsBar({
  tab,
  transport,
  labels: s,
  manage,
  filters,
  onOpen,
}: SavedViewsBarProps) {
  const panelId = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const mounted = useRef(true);
  const [open, setOpen] = useState(false);
  const [openedId, setOpenedId] = useState<string>();
  const [status, setStatus] = useState<OpenStatus>();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function openView(view: WorkSavedView) {
    setStatus({ kind: "opening" });
    const shown = await onOpen(view.definition, view.name);
    if (!mounted.current) return;
    if (shown) {
      setOpenedId(view.id);
      setStatus({ kind: "opened", name: view.name });
      toggle.current?.focus();
    } else {
      setStatus({ kind: "failed", view });
    }
  }

  return (
    <div className="work-saved-views">
      <button
        ref={toggle}
        type="button"
        className="work-saved-views-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        {s.button}
      </button>
      <div className="work-saved-views-status">
        {status?.kind === "opening" && <p role="status">{s.openingView}</p>}
        {status?.kind === "opened" && (
          <p role="status">{s.openedView(status.name)}</p>
        )}
        {status?.kind === "failed" && (
          <p role="alert">
            {s.openFailed}{" "}
            <button
              type="button"
              onClick={() => {
                void openView(status.view);
              }}
            >
              {manage.retry}
            </button>
          </p>
        )}
      </div>
      <div id={panelId} className="work-saved-views-panel" hidden={!open}>
        {open && (
          <SavedViewsPanel
            tab={tab}
            transport={transport}
            labels={s}
            manage={manage}
            filters={filters}
            openedId={openedId}
            opening={status?.kind === "opening"}
            onPick={(view) => {
              void openView(view);
            }}
          />
        )}
      </div>
    </div>
  );
}

type ListPhase = "loading" | "ready" | "error";
/** The row being renamed: its id, the text typed so far, and why the text was refused. */
type EditState = { id: string; value: string; problem?: ViewNameProblem };
/** The last archived view, kept for its Undo line, with the version the archive answered. */
type UndoState = { id: string; name: string; version: number };

type PanelProps = {
  tab: SavedViewTab;
  transport: WorkTransport;
  labels: SavedViewsLabels;
  manage: ManageLabels;
  filters: WorkFilters;
  openedId: string | undefined;
  opening: boolean;
  onPick: (view: WorkSavedView) => void;
};

/**
 * The panel body. It mounts when the bar opens, so every opening reads the list again, and it drops
 * a read that is no longer the newest or that answers after unmount. Writes wait while a read runs,
 * so a list answer never crosses a write.
 */
function SavedViewsPanel({
  tab,
  transport,
  labels: s,
  manage,
  filters,
  openedId,
  opening,
  onPick,
}: PanelProps) {
  const write = useWorkWrite();
  const baseId = useId();
  const nameId = `${baseId}-name`;
  const noteId = `${baseId}-note`;
  const renameNoteId = `${baseId}-rename-note`;
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
  const [views, setViews] = useState<WorkSavedView[]>();
  const [listPhase, setListPhase] = useState<ListPhase>("loading");
  const [showArchived, setShowArchived] = useState(false);
  const [name, setName] = useState("");
  const [nameProblem, setNameProblem] = useState<ViewNameProblem>();
  const [editing, setEditing] = useState<EditState>();
  const [undo, setUndo] = useState<UndoState>();
  const [notice, setNotice] = useState("");

  const { definition, dropped } = filtersToDefinition(tab, filters);
  const blocked = isSaveBlocked(dropped);
  const locked = write.busy || listPhase === "loading";
  const active = (views ?? []).filter((view) => !isArchivedView(view));
  const archived = (views ?? []).filter(isArchivedView);
  const formNote = blocked
    ? s.blockedProject
    : nameProblem === "required"
      ? s.nameRequired
      : nameProblem === "tooLong"
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
            setViews(viewsOfTab(list, tab));
            setListPhase("ready");
          },
          () => {
            if (current !== ticket.current || !mounted.current) return;
            setListPhase("error");
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
    setListPhase("loading");
    loadViews(includeArchived);
  }

  function save() {
    const problem = viewNameProblem(name);
    if (problem) {
      setNameProblem(problem);
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
        setViews((list) => upsertView(list ?? [], result.saved_view));
        setNotice(s.saved(result.saved_view.name));
        setName("");
        setNameProblem(undefined);
        pendingFocus.current = () => nameInput.current?.focus();
      });
  }

  function startRename(view: WorkSavedView) {
    setEditing({ id: view.id, value: view.name });
    pendingFocus.current = () => renameInput.current?.focus();
  }

  function cancelRename(id: string) {
    setEditing(undefined);
    pendingFocus.current = () =>
      buttonFor(panelRef.current, "data-rename", id)?.focus();
  }

  function commitRename(view: WorkSavedView, value: string) {
    const problem = viewNameProblem(value);
    if (problem) {
      setEditing({ id: view.id, value, problem });
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
        setViews((list) => upsertView(list ?? [], result.saved_view));
        setEditing(undefined);
        setNotice(s.renamed(result.saved_view.name));
        pendingFocus.current = () =>
          buttonFor(panelRef.current, "data-rename", view.id)?.focus();
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
        setViews((list) => upsertView(list ?? [], result.saved_view));
        setEditing((current) =>
          current?.id === view.id ? undefined : current,
        );
        setUndo({
          id: result.saved_view.id,
          name: result.saved_view.name,
          version: result.saved_view.version,
        });
        setNotice("");
        pendingFocus.current = () =>
          undoBox.current?.querySelector("button")?.focus();
      });
  }

  /** Restores an archived view; it is listed as active again, and its Open button takes the focus. */
  function restore(id: string, version: number) {
    lastWrite.current = () => restore(id, version);
    void write
      .run(JSON.stringify(["restore-view", id, version]), (key) =>
        transport.restoreSavedWorkView(id, version, key),
      )
      .then((result) => {
        if (!result || !mounted.current) return;
        setViews((list) => upsertView(list ?? [], result.saved_view));
        setUndo((current) => (current?.id === id ? undefined : current));
        setNotice(s.restoredView(result.saved_view.name));
        pendingFocus.current = () =>
          buttonFor(panelRef.current, "data-open", id)?.focus();
      });
  }

  function reload() {
    write.clear();
    readViews(showArchived);
  }

  function toggleArchived(next: boolean) {
    setShowArchived(next);
    readViews(next);
  }

  return (
    <div ref={panelRef} className="work-saved-views-body">
      <form
        className="work-saved-views-save"
        aria-label={s.saveCurrent}
        onSubmit={preventSubmit}
      >
        <p className="work-saved-views-heading">{s.saveCurrent}</p>
        <label htmlFor={nameId}>{s.nameLabel}</label>
        <input
          id={nameId}
          ref={nameInput}
          type="text"
          value={name}
          disabled={locked}
          aria-invalid={nameProblem ? true : undefined}
          aria-describedby={formNote ? noteId : undefined}
          onChange={(event) => {
            setNameProblem(undefined);
            setName(event.target.value);
          }}
          onKeyDown={(event) => onEnterKey(event, save)}
        />
        {formNote && <p id={noteId}>{formNote}</p>}
        <button
          type="button"
          className="sk-btn--primary"
          disabled={locked || blocked}
          onClick={save}
        >
          {s.save}
        </button>
      </form>
      <WriteNotice
        failure={write.failure}
        labels={manage}
        onReload={reload}
        onRetry={() => lastWrite.current?.()}
      />
      {listPhase === "loading" && <p role="status">{s.listLoading}</p>}
      {listPhase === "error" ? (
        <p role="alert">
          {s.listFailed}{" "}
          <button type="button" onClick={() => readViews(showArchived)}>
            {manage.retry}
          </button>
        </p>
      ) : views === undefined ? null : active.length > 0 ? (
        <ul className="work-saved-views-list">
          {active.map((view) => {
            const edit = editing?.id === view.id ? editing : undefined;
            return edit ? (
              <li key={view.id} className="work-saved-view">
                <form
                  className="work-saved-view-rename"
                  aria-label={s.renameFor(view.name)}
                  onSubmit={preventSubmit}
                >
                  <input
                    ref={renameInput}
                    type="text"
                    aria-label={s.nameLabel}
                    value={edit.value}
                    disabled={locked}
                    aria-invalid={edit.problem ? true : undefined}
                    aria-describedby={edit.problem ? renameNoteId : undefined}
                    onChange={(event) =>
                      setEditing({ id: view.id, value: event.target.value })
                    }
                    onKeyDown={(event) =>
                      onEnterKey(event, () => commitRename(view, edit.value))
                    }
                  />
                  {edit.problem && (
                    <p id={renameNoteId}>
                      {edit.problem === "required"
                        ? s.nameRequired
                        : s.nameTooLong}
                    </p>
                  )}
                  <div className="work-manage-controls">
                    <button
                      type="button"
                      className="sk-btn--primary"
                      disabled={locked}
                      onClick={() => commitRename(view, edit.value)}
                    >
                      {s.save}
                    </button>
                    <button
                      type="button"
                      disabled={locked}
                      onClick={() => cancelRename(view.id)}
                    >
                      {s.cancel}
                    </button>
                  </div>
                </form>
              </li>
            ) : (
              <li key={view.id} className="work-saved-view">
                <span className="work-saved-view-name">{view.name}</span>
                {openedId === view.id && (
                  <span className="work-saved-view-mark">{s.opened}</span>
                )}
                <div className="work-manage-controls">
                  <button
                    type="button"
                    data-open={view.id}
                    aria-label={s.openFor(view.name)}
                    disabled={locked || opening}
                    onClick={() => onPick(view)}
                  >
                    {s.open}
                  </button>
                  <button
                    type="button"
                    data-rename={view.id}
                    aria-label={s.renameFor(view.name)}
                    disabled={locked}
                    onClick={() => startRename(view)}
                  >
                    {s.rename}
                  </button>
                  <button
                    type="button"
                    aria-label={manage.archiveFor(view.name)}
                    disabled={locked}
                    onClick={() => archive(view)}
                  >
                    {manage.archive}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p>{s.empty}</p>
      )}
      {undo && (
        <div ref={undoBox}>
          <UndoLine
            text={s.archivedView(undo.name)}
            disabled={locked}
            labels={manage}
            onUndo={() => restore(undo.id, undo.version)}
          />
        </div>
      )}
      <p role="status" className="work-saved-views-notice">
        {notice}
      </p>
      <label className="work-saved-views-archived-toggle">
        <input
          type="checkbox"
          checked={showArchived}
          disabled={locked}
          onChange={(event) => toggleArchived(event.target.checked)}
        />
        {s.showArchived}
      </label>
      {showArchived &&
        views !== undefined &&
        (archived.length > 0 ? (
          <ArchivedRows
            items={archived.map((view) => ({ id: view.id, title: view.name }))}
            disabled={locked}
            labels={manage}
            onRestore={(id) => {
              const view = archived.find((item) => item.id === id);
              if (view) restore(view.id, view.version);
            }}
          />
        ) : (
          <p>{s.noArchived}</p>
        ))}
    </div>
  );
}

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
