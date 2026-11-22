import { useContext, useEffect, useRef, useState } from "react";
import {
  EntryChangeButtons,
  EntryLinked,
  EntryWhen,
  editRefusalText,
  tagFailureText,
} from "./entry-parts";
import { mergeFields } from "./draft-review";
import { EntryEditForm } from "./entry-edit";
import { EntryNeighbours, useEntryNeighbours } from "./entry-neighbours";
import type { Side } from "./entry-neighbours";
import { EntryReadBody, useEntrySource } from "./entry-read";
import { EntryTextForm } from "./entry-write";
import { isNotFound } from "../../lib/mcp/errors";
import { keyFor } from "../mcp-apps/idempotency";
import type { PendingKey } from "../mcp-apps/idempotency";
import { receiptText } from "./receipt-text";
import { isForbidden, writeFailure } from "./transport";
import type {
  JournalDraftFields,
  JournalEntry,
  JournalFrame,
} from "./transport";
import {
  BackHeaderActions,
  useBackHeaderSlot,
} from "../mcp-apps/ui/back-header";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { ReceiptBar, useReceipt } from "../mcp-apps/ui/receipt";
import { RoomSurfaceContext } from "../mcp-apps/ui/room-context";
import { useRoomShortcuts } from "../mcp-apps/ui/shortcut-registry";
import { TagField } from "../mcp-apps/ui/tags";
import { useTagVocabulary } from "../mcp-apps/ui/tag-vocabulary";
import {
  EntryMenu,
  EntryTrashed,
  EntryTrashFailure,
  useEntryTrash,
} from "./entry-trash";
import type { FrameProps, LoadPhase } from "./frame-props";
import { EntryMemoryFailure, MemoryChip, useEntryMemory } from "./entry-memory";
import { isQueued, useQueuedRecords } from "./use-queued-records";
import "./entry.css";
import "./entry-read.css";

/** The saved entry offers at most this many "Open the task" buttons, one per created task. */
const taskOpenLimit = 3;

export function EntryFrame({
  id,
  notice,
  transport,
  labels: t,
  moves,
  onOpen,
  onOpenContact,
  onOpenProject,
  onOpenTask,
  refreshKey,
  onStep,
  fullscreen = true,
}: FrameProps & {
  id: string;
  notice?: { created: number; updated: number; createdTaskIds?: string[] };
  onOpen: (frame: JournalFrame) => void;
  onOpenContact?: (link: { id: string; label: string | null }) => void;
  onOpenProject?: (link: { id: string; label: string | null }) => void;
  onOpenTask?: (id: string) => void;
  refreshKey?: number;
  /**
   * Opens the previous or next entry. Absent: `onOpen` does, which adds a layer. A view that shows the entry in a pane
   * beside its list gives a step that replaces the entry in place, so stepping builds no stack.
   */
  onStep?: (id: string) => void;
  /** The keys (`e`, `j`, `k`) work in fullscreen only; an inline view has none. */
  fullscreen?: boolean;
}) {
  const [phase, setPhase] = useState<LoadPhase | "gone">("loading");
  const [cause, setCause] = useState<unknown>();
  const [entry, setEntry] = useState<JournalEntry>();
  const [attempt, setAttempt] = useState(0);
  // Editing by hand (see docs/decisions/log.md D-076: the journal is written by hand, no AI): which form is open, how the last write failed, what it changed, and its key.
  const [mode, setMode] = useState<"view" | "edit" | "append">("view");
  const [editFailure, setEditFailure] = useState<
    ReturnType<typeof writeFailure> | undefined
  >();
  const [editing, setEditing] = useState(false);
  const editKey = useRef<PendingKey | undefined>(undefined);
  // The tags are written on their own, as one update of the complete set; the key and the failure are theirs too.
  const [tagBusy, setTagBusy] = useState(false);
  const [tagFailure, setTagFailure] = useState<
    ReturnType<typeof writeFailure> | undefined
  >();
  const tagKey = useRef<PendingKey | undefined>(undefined);
  const vocabulary = useTagVocabulary(transport.listTags, "journal_entry");
  const heading = useRef<HTMLHeadingElement>(null);
  const queuedIds = useQueuedRecords(transport);
  // Every confirmation ("Anteckningen är ändrad") is one floating bar at the foot of the view, never a line in the
  // content; it belongs to this entry and goes away with it (resetKey) and by itself.
  const receipt = useReceipt(id);
  const { show: showReceipt } = receipt;
  const trashState = useEntryTrash(transport, entry, reloadEntry);
  // Out of memory or back in: the version does not change, so the shown entry only flips its flag.
  const memory = useEntryMemory(transport, entry, (excluded) => {
    if (entry) entryChanged({ ...entry, memory_excluded: excluded });
    showReceipt({
      message: receiptText(
        excluded ? t.entryKeptOutOfMemory : t.entryBackInMemory,
      ),
    });
  });
  const inShell = useBackHeaderSlot();
  const { pane } = useContext(RoomSurfaceContext);
  const source = useEntrySource(transport, entry);
  const { neighbours, resolve } = useEntryNeighbours(transport, entry);
  const [stepping, setStepping] = useState(false);
  // The Projects and Contacts show by name when the entry carries its links; an older entry shows the
  // counts. Tasks are not links in the record: they show by title when the host can read them (EntryTasks), else as
  // a count. Only what is really linked is listed; with nothing to list, the whole "Linked" block is hidden.
  const named = entry?.links ?? [];
  const tasks = entry?.task_ids ?? [];
  const counts = entry
    ? [
        ...(entry.links === undefined
          ? [{ label: t.projects, count: entry.project_ids.length }]
          : []),
        ...(entry.links === undefined
          ? [{ label: t.contacts, count: entry.contact_ids.length }]
          : []),
      ].filter((link) => link.count > 0)
    : [];
  // The saved draft's notice ("Anteckningen sparades"): shown once as the receipt of the save that opened this entry.
  useEffect(() => {
    if (notice)
      showReceipt({
        message: receiptText(t.entrySaved(notice.created, notice.updated)),
      });
  }, [notice, showReceipt, t]);
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);
  const isTrashed = trashState.trashed !== undefined;
  useEffect(() => {
    if (isTrashed) heading.current?.focus();
  }, [isTrashed]);
  // Counts the reads and the link writes: an answer from a read that is not the latest is dropped.
  const ticket = useRef(0);
  useEffect(() => {
    const marker = ticket;
    const current = ++marker.current;
    // The app asks for content itself: the user opened their own entry. A changed refreshKey reads it
    // again without the loading state, so the shown entry stays until the answer replaces it.
    transport
      .getEntry(id)
      .then(({ entry: loaded }) => {
        if (current !== marker.current) return;
        setEntry(loaded);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (current !== marker.current) return;
        setCause(error);
        if (isForbidden(error)) setPhase("forbidden");
        else if (isNotFound(error)) setPhase("gone");
        else setPhase("error");
      });
    return () => {
      marker.current++;
    };
  }, [transport, id, attempt, refreshKey]);
  /**
   * The answer of a link write is newer than any read of this entry still on its way: that read is
   * dropped, so it cannot put the entry as it was before the write back. The phase is cleared here, in
   * case the dropped read was the one to do it.
   */
  function entryChanged(changed: JournalEntry) {
    ticket.current++;
    setPhase("ready");
    setEntry(changed);
  }
  /** A stale version: the entry is read again and the forms keep what the owner wrote. */
  function reloadEntry() {
    transport.getEntry(id).then(
      ({ entry: loaded }) => entryChanged(loaded),
      () => undefined,
    );
  }
  function closeForm(note: string) {
    setMode("view");
    setEditFailure(undefined);
    if (note) showReceipt({ message: receiptText(note) });
    heading.current?.focus();
  }
  function saveEdit(changes: Partial<JournalDraftFields>) {
    const write = transport.updateEntry;
    if (!write || !entry || editing) return;
    // Nothing changed: nothing is written, the version stays.
    if (Object.keys(changes).length === 0) {
      closeForm("");
      return;
    }
    const fields = mergeFields(entry, changes);
    const pending = keyFor(
      editKey.current,
      JSON.stringify(["edit", entry.id, entry.version, fields]),
    );
    editKey.current = pending;
    setEditing(true);
    setEditFailure(undefined);
    write(entry.id, entry.version, fields, pending.key)
      .then((result) => {
        editKey.current = undefined;
        entryChanged(result.entry);
        closeForm(t.entryUpdated);
      })
      .catch((error: unknown) => {
        const how = writeFailure(error);
        setEditFailure(how);
        if (how === "conflict") reloadEntry();
      })
      .finally(() => setEditing(false));
  }
  const canTrash =
    Boolean(transport.trashEntry && transport.restoreEntry) &&
    phase === "ready" &&
    entry !== undefined &&
    mode === "view" &&
    !trashState.trashed;
  function restoreEntry() {
    trashState.restore(() => {
      reloadEntry();
      showReceipt({ message: receiptText(t.entryRestored) });
      heading.current?.focus();
    });
  }
  /** Writes the complete tag set at the entry's version; `done` runs once it is stored. A failed write can be retried as it was. */
  function saveTags(next: string[], done: () => void) {
    const write = transport.updateEntryTags;
    if (!write || !entry || tagBusy) return;
    const pending = keyFor(
      tagKey.current,
      JSON.stringify(["tags", entry.id, entry.version, next]),
    );
    tagKey.current = pending;
    setTagBusy(true);
    setTagFailure(undefined);
    write(entry.id, entry.version, next, pending.key)
      .then((result) => {
        tagKey.current = undefined;
        entryChanged(result.entry);
        vocabulary.refresh();
        done();
      })
      .catch((error: unknown) => {
        const how = writeFailure(error);
        setTagFailure(how);
        if (how === "conflict") reloadEntry();
      })
      .finally(() => setTagBusy(false));
  }
  function appendText(text: string, idempotencyKey: string): Promise<void> {
    const write = transport.appendEntryText;
    if (!write || !entry) return Promise.reject(new Error("no append"));
    return write(entry.id, entry.version, text, idempotencyKey).then(
      (result) => {
        entryChanged(result.entry);
        closeForm(t.entryTextAdded);
      },
    );
  }
  const canEdit =
    phase === "ready" && entry && !entry.archived && mode === "view";
  const canChange =
    canEdit &&
    !trashState.trashed &&
    (transport.updateEntry !== undefined ||
      transport.appendEntryText !== undefined);
  function startEdit() {
    if (!canChange || !transport.updateEntry) return;
    receipt.clear();
    setMode("edit");
  }
  function startAppend() {
    receipt.clear();
    setMode("append");
  }
  /** Opens the entry before or after this one; the day is read first when only the day is known. */
  function step(side: Side) {
    if (stepping || mode !== "view") return;
    setStepping(true);
    void resolve(side)
      .then((next) => {
        if (next) (onStep ?? ((to) => onOpen({ kind: "entry", id: to })))(next);
      })
      .finally(() => setStepping(false));
  }
  // `e` changes the entry. `j` and `k` step through the day's entries when no list stands beside the entry: in a
  // split the list owns them and each step there opens the neighbour in this pane.
  useRoomShortcuts(
    {
      ...(canChange && transport.updateEntry ? { e: startEdit } : {}),
      ...(pane === "detail"
        ? {}
        : { j: () => step("next"), k: () => step("previous") }),
    },
    {
      id: "journal-entry",
      title: t.title,
      labels: {
        e: t.editEntry,
        j: t.nextEntry,
        k: t.previousEntry,
      },
    },
    { enabled: fullscreen && phase === "ready" && mode === "view" },
  );
  // A refused edit explains itself; a failed save is the editor's own row with Försök igen.
  const refusal = editRefusalText(editFailure, t);
  // What the entry is linked to: drawn in the reading view's fold, and in the editor, where a link can be removed.
  const linked =
    entry && (named.length > 0 || counts.length > 0 || tasks.length > 0) ? (
      <EntryLinked
        entry={entry}
        labels={t}
        counts={counts}
        transport={transport}
        receipt={receipt}
        onOpenContact={onOpenContact}
        onOpenProject={onOpenProject}
        onOpenTask={onOpenTask}
        onChanged={entryChanged}
        onEmptied={() => heading.current?.focus()}
        onConflict={reloadEntry}
        removable={mode === "edit"}
      />
    ) : null;
  // Pen and plus sit in the detail's head, beside ⋯; where no head offers a place (inline, a test) they are the two
  // buttons under the date, as before.
  const changes = canChange ? (
    <EntryChangeButtons
      labels={t}
      canEdit={transport.updateEntry !== undefined}
      canAppend={transport.appendEntryText !== undefined}
      onEdit={startEdit}
      onAppend={startAppend}
    />
  ) : null;

  return (
    <article className="journal-entry-view">
      <h2
        ref={heading}
        tabIndex={-1}
        className={
          mode === "edit"
            ? "journal-entry-title journal-visually-hidden"
            : "journal-entry-title"
        }
      >
        {phase === "ready" && entry ? entry.title : t.entry}
      </h2>
      {notice && onOpenTask && notice.createdTaskIds && (
        <ul className="journal-chips">
          {notice.createdTaskIds.slice(0, taskOpenLimit).map((taskId) => (
            <li key={taskId}>
              <button
                type="button"
                className="sk-btn--quiet"
                onClick={() => onOpenTask(taskId)}
              >
                {t.openTask}
              </button>
            </li>
          ))}
        </ul>
      )}
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.forbidden}</p>}
      {phase === "gone" && <p>{t.entryGone}</p>}
      {phase === "error" && (
        <ErrorNotice
          locale={t.dateLocale}
          cause={cause}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      )}
      {inShell && changes && <BackHeaderActions>{changes}</BackHeaderActions>}
      {canTrash && (
        <EntryMenu
          labels={t}
          disabled={trashState.busy || memory?.busy === true}
          onTrash={trashState.trash}
          onToggleMemory={memory?.toggle}
          memoryExcluded={entry?.memory_excluded === true}
        />
      )}
      {phase === "ready" && entry && trashState.trashed && (
        <EntryTrashed labels={t} state={trashState} onRestore={restoreEntry} />
      )}
      {phase === "ready" && entry && !trashState.trashed && (
        <>
          {trashState.failure?.action === "trash" && (
            <EntryTrashFailure
              labels={t}
              how={trashState.failure.how}
              busy={trashState.busy}
              onRetry={trashState.trash}
            />
          )}
          {memory && <EntryMemoryFailure labels={t} state={memory} />}
          {/* The day with its weekday and the time, then the tags on the same line when there is room. While the
              entry is edited the form carries the day, so this line goes. */}
          <div className="journal-entry-when">
            {mode !== "edit" && (
              <EntryWhen
                entry={entry}
                labels={t}
                queued={isQueued(queuedIds, entry.id)}
              />
            )}
            {/* Changed in place (no form); an archived entry shows its tags only. */}
            <TagField
              tags={entry.tags ?? []}
              suggestions={vocabulary.suggestions}
              editable={
                transport.updateEntryTags !== undefined &&
                !entry.archived &&
                mode === "view"
              }
              busy={tagBusy}
              name={entry.title}
              onChange={saveTags}
              locale={t.dateLocale}
            />
          </div>
          {entry.archived && <p className="journal-muted">{t.archived}</p>}
          {entry.memory_excluded && <MemoryChip labels={t} />}
          {tagFailure && (
            <ErrorNotice
              placement="row"
              locale={t.dateLocale}
              message={tagFailureText(tagFailure, t)}
            />
          )}
          {!inShell && changes && (
            <div className="journal-actions">
              {transport.updateEntry && (
                <button
                  type="button"
                  className="sk-btn--secondary"
                  onClick={startEdit}
                >
                  {t.editEntry}
                </button>
              )}
              {transport.appendEntryText && (
                <button
                  type="button"
                  className="sk-btn--secondary"
                  onClick={startAppend}
                >
                  {t.appendText}
                </button>
              )}
            </div>
          )}
          {mode === "edit" && transport.updateEntry && (
            <>
              {refusal && (
                <ErrorNotice
                  placement="row"
                  locale={t.dateLocale}
                  message={refusal}
                />
              )}
              <EntryEditForm
                draft={entry}
                date={entry.journal_date}
                summaryByOwner={entry.summary_by === "you"}
                busy={editing}
                saveFailed={
                  editFailure === "failed" || editFailure === "not_found"
                }
                onSave={saveEdit}
                onCancel={() => {
                  editKey.current = undefined;
                  setEditFailure(undefined);
                  setMode("view");
                  heading.current?.focus();
                }}
                labels={t}
              />
              {linked}
            </>
          )}
          {mode !== "edit" && (
            <EntryReadBody
              entry={entry}
              state={source}
              labels={t}
              onShowOriginal={
                transport.getSource
                  ? () => onOpen({ kind: "source", id: entry.source_id })
                  : undefined
              }
              linked={linked}
            />
          )}
          {mode === "append" && transport.appendEntryText && (
            <EntryTextForm
              labels={t}
              kind="append"
              date={entry.journal_date}
              signatureBase={`${entry.id}:${entry.version}`}
              submit={(values, key) => appendText(values.text, key)}
              onCancel={() => setMode("view")}
              onConflict={reloadEntry}
            />
          )}
          {mode === "view" && (
            <EntryNeighbours
              labels={t}
              neighbours={neighbours}
              disabled={stepping}
              onStep={step}
            />
          )}
        </>
      )}
      <ReceiptBar receipt={receipt} />
    </article>
  );
}
