import { useEffect, useRef, useState } from "react";
import { formatShortDateWithYear, formatTime } from "./dates";
import { EntryLinks } from "./entry-links";
import { EntryTasks } from "./entry-tasks";
import { FieldsEditor, mergeFields } from "./draft-review";
import { EntryTextForm } from "./entry-write";
import { ownerToday } from "../mcp-apps/app-timezone";
import { keyFor } from "../mcp-apps/idempotency";
import type { PendingKey } from "../mcp-apps/idempotency";
import { originalLine, summaryRest } from "./entry-card";
import { labelFor } from "./labels";
import { isForbidden, writeFailure } from "./transport";
import type {
  JournalDraftFields,
  JournalEntry,
  JournalFrame,
} from "./transport";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { TagField } from "../mcp-apps/ui/tags";
import { useTagVocabulary } from "../mcp-apps/ui/tag-vocabulary";
import {
  EntryMenu,
  EntryTrashed,
  EntryTrashFailure,
  useEntryTrash,
} from "./entry-trash";
import type { FrameProps, LoadPhase } from "./frame-props";

/** The saved entry offers at most this many "Open the task" buttons, one per created task. */
const taskOpenLimit = 3;

/**
 * True when the server says the entry is gone (deleted while the owner was in another view). Such a
 * refusal is not transient either: the view shows a calm line, not retry.
 */
function isNotFound(error: unknown): boolean {
  return (error as { code?: unknown } | null | undefined)?.code === "not_found";
}

export function EntryFrame({
  id,
  notice,
  transport,
  labels: t,
  moves,
  onOpen,
  onOpenContact,
  onOpenTask,
  refreshKey,
}: FrameProps & {
  id: string;
  notice?: { created: number; updated: number; createdTaskIds?: string[] };
  onOpen: (frame: JournalFrame) => void;
  onOpenContact?: (link: { id: string; label: string | null }) => void;
  onOpenTask?: (id: string) => void;
  refreshKey?: number;
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
  const [changedNote, setChangedNote] = useState<string>();
  const editKey = useRef<PendingKey | undefined>(undefined);
  // The tags are written on their own, as one update of the complete set; the key and the failure are theirs too.
  const [tagBusy, setTagBusy] = useState(false);
  const [tagFailure, setTagFailure] = useState<
    ReturnType<typeof writeFailure> | undefined
  >();
  const tagKey = useRef<PendingKey | undefined>(undefined);
  const vocabulary = useTagVocabulary(transport.listTags, "journal_entry");
  const heading = useRef<HTMLHeadingElement>(null);
  const trashState = useEntryTrash(transport, entry, reloadEntry);
  // The title is the heading above. A summary that repeats it shows only the rest, as the card does.
  const rest = entry ? summaryRest(entry.title, entry.summary) : undefined;
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
    setChangedNote(note);
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
      setChangedNote(t.entryRestored);
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

  return (
    <article>
      <h2 ref={heading} tabIndex={-1}>
        {phase === "ready" && entry ? entry.title : t.entry}
      </h2>
      {notice && (
        <p role="status">{t.entrySaved(notice.created, notice.updated)}</p>
      )}
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
      {canTrash && (
        <EntryMenu
          labels={t}
          disabled={trashState.busy}
          onTrash={trashState.trash}
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
          <p>
            {formatShortDateWithYear(
              entry.journal_date,
              t.dateLocale,
              ownerToday(),
            )}
            {entry.occurred_at && (
              <>
                {" · "}
                <time dateTime={entry.occurred_at}>
                  {formatTime(entry.occurred_at, t.dateLocale)}
                </time>
              </>
            )}
          </p>
          {entry.archived && <p className="journal-muted">{t.archived}</p>}
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
          {tagFailure && (
            <p role="alert" className="journal-banner">
              {tagFailure === "conflict"
                ? t.tagsConflict
                : tagFailure === "invalid"
                  ? t.tagsInvalid
                  : tagFailure === "forbidden"
                    ? t.forbiddenWrite
                    : t.tagsFailed}
            </p>
          )}
          {changedNote && <p role="status">{changedNote}</p>}
          {canEdit && (transport.updateEntry || transport.appendEntryText) && (
            <div className="journal-actions">
              {transport.updateEntry && (
                <button
                  type="button"
                  className="sk-btn--secondary"
                  onClick={() => {
                    setChangedNote(undefined);
                    setMode("edit");
                  }}
                >
                  {t.editEntry}
                </button>
              )}
              {transport.appendEntryText && (
                <button
                  type="button"
                  className="sk-btn--secondary"
                  onClick={() => {
                    setChangedNote(undefined);
                    setMode("append");
                  }}
                >
                  {t.appendText}
                </button>
              )}
            </div>
          )}
          {mode === "edit" && transport.updateEntry && (
            <>
              {editFailure === "conflict" && (
                <p role="alert">{t.entryEditConflict}</p>
              )}
              {editFailure === "invalid" && (
                <p role="alert">{t.entryInvalid}</p>
              )}
              {editFailure === "forbidden" && (
                <p role="alert">{t.forbiddenWrite}</p>
              )}
              <FieldsEditor
                draft={entry}
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
                confirmDiscard
                labels={t}
              />
            </>
          )}
          {mode === "append" && transport.appendEntryText && (
            <EntryTextForm
              labels={t}
              kind="append"
              signatureBase={`${entry.id}:${entry.version}`}
              submit={(values, key) => appendText(values.text, key)}
              onCancel={() => setMode("view")}
              onConflict={reloadEntry}
            />
          )}
          {mode !== "edit" && rest && <p className="journal-summary">{rest}</p>}
          {/* The original is always saved with an entry, so the line and its button always show here. */}
          <div className="journal-original-row">
            <p className="journal-muted">{originalLine(entry.summary, t)}</p>
            {transport.getSource && (
              <button
                type="button"
                className="sk-btn--quiet journal-toggle"
                onClick={() => onOpen({ kind: "source", id: entry.source_id })}
              >
                {t.showOriginal}
              </button>
            )}
          </div>
          {mode !== "edit" && entry.key_points.length > 0 && (
            <>
              <h3>{t.keyPoints}</h3>
              <ul className="journal-list">
                {entry.key_points.map((point, index) => (
                  <li key={index}>
                    <p>
                      {labelFor(t.keyPointKind, point.kind)}: {point.text}
                    </p>
                  </li>
                ))}
              </ul>
            </>
          )}
          {(named.length > 0 || counts.length > 0 || tasks.length > 0) && (
            <h3>{t.linked}</h3>
          )}
          {/* The names, each with its × that asks before it removes the link. The inline card shows the links as
              text only, so this is where a link is removed. Drawn whenever the entry
              carries its links, so the Undo line stays after the last link is removed. */}
          {entry.links !== undefined && (
            <EntryLinks
              entry={entry}
              labels={t}
              transport={transport}
              onOpenContact={onOpenContact}
              onChanged={entryChanged}
              onConflict={reloadEntry}
              removable={mode === "edit"}
            />
          )}
          <EntryTasks
            taskIds={tasks}
            labels={t}
            getTaskTitle={transport.getTaskTitle}
            onOpenTask={onOpenTask}
          />
          {counts.length > 0 && (
            <ul className="journal-list">
              {counts.map((link) => (
                <li key={link.label}>
                  {link.label}: {link.count}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </article>
  );
}
