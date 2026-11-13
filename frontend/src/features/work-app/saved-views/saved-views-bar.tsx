import { useEffect, useId, useRef, useState } from "react";
import { onEnterKey, preventSubmit } from "../../mcp-apps/ui/enter-key";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { ArchivedRows, UndoLine, WriteNotice } from "../shared/manage-controls";
import type { WorkLabels } from "../shared/labels";
import type { ManageLabels } from "../shared/manage-labels";
import type { SavedViewsLabels } from "./saved-views-labels";
import { describeDefinition, type SavedViewTab } from "./saved-views";
import type {
  WorkFilters,
  WorkSavedView,
  WorkSavedViewDefinition,
  WorkTransport,
} from "../transport/transport";
import { useSavedViewsPanel } from "./use-saved-views-panel";
import "./saved-views.css";

export type SavedViewsBarProps = {
  /** The tab the bar belongs to; only views saved for this tab are listed. */
  tab: SavedViewTab;
  transport: WorkTransport;
  labels: SavedViewsLabels;
  /** The Work words, for the status and priority names a view's summary line uses. */
  workLabels: WorkLabels;
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

type OpenStatus = { kind: "opening" } | { kind: "failed"; view: WorkSavedView };

/**
 * The saved views of one Work tab: a visible "Sparade vyer" button that unfolds a panel. The panel
 * reads the list only when it opens, and holds the list of this tab's views (a row opens the view;
 * "Ändra" unfolds rename and archive), the save form and the archived views (restore). Opening a
 * view is reported back through onOpen and folds the panel away, so the opened list is in sight; the
 * caller shows which view is open. The "opening" and "failed" lines stay visible with the panel closed.
 */
export function SavedViewsBar({
  tab,
  transport,
  labels: s,
  workLabels,
  manage,
  filters,
  onOpen,
}: SavedViewsBarProps) {
  const panelId = useId();
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
      setStatus(undefined);
      setOpen(false);
    } else {
      setStatus({ kind: "failed", view });
    }
  }

  return (
    <div className="work-saved-views">
      <button
        type="button"
        className="sk-menu-item work-saved-views-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        {s.button}
      </button>
      <div className="work-saved-views-status">
        {status?.kind === "opening" && <p role="status">{s.openingView}</p>}
        {status?.kind === "failed" && (
          <ErrorNotice
            placement="row"
            locale={manage.dateLocale}
            message={s.openFailed}
            onRetry={() => {
              void openView(status.view);
            }}
          />
        )}
      </div>
      <div id={panelId} className="work-saved-views-panel" hidden={!open}>
        {open && (
          <SavedViewsPanel
            tab={tab}
            transport={transport}
            labels={s}
            workLabels={workLabels}
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

type PanelProps = {
  tab: SavedViewTab;
  transport: WorkTransport;
  labels: SavedViewsLabels;
  workLabels: WorkLabels;
  manage: ManageLabels;
  filters: WorkFilters;
  openedId: string | undefined;
  opening: boolean;
  onPick: (view: WorkSavedView) => void;
};

/** The panel body. It mounts when the bar opens, so every opening reads the list again. */
function SavedViewsPanel({
  tab,
  transport,
  labels: s,
  workLabels,
  manage,
  filters,
  openedId,
  opening,
  onPick,
}: PanelProps) {
  const panel = useSavedViewsPanel({ tab, transport, labels: s, filters });
  const {
    state,
    write,
    blocked,
    definition,
    locked,
    active,
    archivedViews,
    formNote,
  } = panel;
  // The row whose "Ändra" is unfolded (rename, archive); one at a time.
  const [editMenuId, setEditMenuId] = useState<string>();
  const {
    views,
    listPhase,
    showArchived,
    name,
    nameProblem,
    editing,
    undo,
    notice,
  } = state;
  const { panelRef, nameInput, renameInput, undoBox } = panel;
  const baseId = useId();
  const nameId = `${baseId}-name`;
  const noteId = `${baseId}-note`;
  const renameNoteId = `${baseId}-rename-note`;
  return (
    <div ref={panelRef} className="work-saved-views-body">
      {listPhase === "loading" && <p role="status">{s.listLoading}</p>}
      {listPhase === "error" ? (
        <ErrorNotice
          placement="row"
          locale={manage.dateLocale}
          message={s.listFailed}
          onRetry={() => panel.readViews(showArchived)}
        />
      ) : views === undefined ? null : active.length > 0 ? (
        <ul className="work-saved-views-list">
          {active.map((view) => {
            const edit = editing?.id === view.id ? editing : undefined;
            if (edit)
              return (
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
                        panel.typeRename(view.id, event.target.value)
                      }
                      onKeyDown={(event) =>
                        onEnterKey(event, () =>
                          panel.commitRename(view, edit.value),
                        )
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
                        onClick={() => panel.commitRename(view, edit.value)}
                      >
                        {s.save}
                      </button>
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => panel.cancelRename(view.id)}
                      >
                        {s.cancel}
                      </button>
                    </div>
                  </form>
                </li>
              );
            const isOpen = openedId === view.id;
            const unfolded = editMenuId === view.id;
            const summary = describeDefinition(view.definition, s, workLabels);
            return (
              <li key={view.id} className="work-saved-view">
                <div className="work-saved-view-row">
                  <button
                    type="button"
                    className="work-saved-view-open"
                    data-open={view.id}
                    aria-labelledby={`${baseId}-${view.id}-name`}
                    aria-describedby={`${baseId}-${view.id}-meta`}
                    aria-current={isOpen ? "true" : undefined}
                    disabled={locked || opening}
                    onClick={() => onPick(view)}
                  >
                    <span
                      id={`${baseId}-${view.id}-name`}
                      className="work-saved-view-name"
                    >
                      {view.name}
                    </span>
                    <span
                      id={`${baseId}-${view.id}-meta`}
                      className="work-saved-view-meta"
                    >
                      {isOpen ? `${s.opened} · ${summary}` : summary}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="work-saved-view-edit"
                    data-edit={view.id}
                    aria-label={s.editFor(view.name)}
                    aria-expanded={unfolded}
                    aria-controls={`${baseId}-${view.id}-edit`}
                    disabled={locked}
                    onClick={() =>
                      setEditMenuId(unfolded ? undefined : view.id)
                    }
                  >
                    {s.edit}
                  </button>
                </div>
                {unfolded && (
                  <div
                    id={`${baseId}-${view.id}-edit`}
                    className="work-manage-controls work-saved-view-edit-menu"
                  >
                    <button
                      type="button"
                      data-rename={view.id}
                      aria-label={s.renameFor(view.name)}
                      disabled={locked}
                      onClick={() => {
                        setEditMenuId(undefined);
                        panel.startRename(view);
                      }}
                    >
                      {s.rename}
                    </button>
                    <button
                      type="button"
                      aria-label={manage.archiveFor(view.name)}
                      disabled={locked}
                      onClick={() => {
                        setEditMenuId(undefined);
                        panel.archive(view);
                      }}
                    >
                      {manage.archive}
                    </button>
                  </div>
                )}
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
            onUndo={() => panel.restore(undo.id, undo.version)}
          />
        </div>
      )}
      <p role="status" className="work-saved-views-notice">
        {notice}
      </p>
      <WriteNotice
        failure={write.failure}
        labels={manage}
        onReload={panel.reload}
        onRetry={panel.retryWrite}
      />
      <label className="work-saved-views-archived-toggle">
        <input
          type="checkbox"
          checked={showArchived}
          disabled={locked}
          onChange={(event) => panel.toggleArchived(event.target.checked)}
        />
        {s.showArchived}
      </label>
      {showArchived &&
        views !== undefined &&
        (archivedViews.length > 0 ? (
          <ArchivedRows
            items={archivedViews.map((view) => ({
              id: view.id,
              title: view.name,
            }))}
            disabled={locked}
            labels={manage}
            onRestore={(id) => {
              const view = archivedViews.find((item) => item.id === id);
              if (view) panel.restore(view.id, view.version);
            }}
          />
        ) : (
          <p>{s.noArchived}</p>
        ))}
      <form
        className="work-saved-views-save"
        aria-label={s.saveCurrent}
        onSubmit={preventSubmit}
      >
        <p className="work-saved-views-heading">{s.saveCurrent}</p>
        <p className="work-saved-views-meta">
          {s.savingNow(describeDefinition(definition, s, workLabels))}
        </p>
        <label htmlFor={nameId}>{s.nameLabel}</label>
        <input
          id={nameId}
          ref={nameInput}
          type="text"
          value={name}
          disabled={locked}
          aria-invalid={nameProblem ? true : undefined}
          aria-describedby={formNote ? noteId : undefined}
          onChange={(event) => panel.changeName(event.target.value)}
          onKeyDown={(event) => onEnterKey(event, panel.save)}
        />
        {formNote && <p id={noteId}>{formNote}</p>}
        <button
          type="button"
          className="sk-btn--primary"
          disabled={locked || blocked}
          onClick={panel.save}
        >
          {s.save}
        </button>
      </form>
    </div>
  );
}
