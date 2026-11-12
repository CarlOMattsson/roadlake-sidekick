import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { EmptyState } from "../mcp-apps/ui/states";
import {
  actionName,
  actorName,
  kindName,
  sourceName,
  stateName,
  type ControlLabels,
} from "./labels";
import { ControlRow, NoticeLine, RowList, type Notice } from "./control-parts";
import {
  canUndo,
  writeFailure,
  type ActivityList,
  type ChangeRecord,
  type ChangesList,
  type ControlTransport,
  type TrashItem,
} from "./transport";
import { whenText } from "./when";

/**
 * History as one list, newest first: the changes (Undo when the server named an existing tool for it,
 * set_shopping_item_purchased; Restore when the record is in the trash, the same restore_from_trash call as
 * the trash card) and the assistant's activity (read only). A row without an action has nothing at the end.
 * Either part may be missing (its read failed or has not come yet); the list shows what there is.
 */
export function HistoryView({
  changes: initial,
  activity,
  transport,
  labels,
  now = () => new Date(),
  onData,
  sendMessage,
  onModelContext,
  expanded,
  onExpandedChange,
}: {
  changes?: ChangesList;
  activity?: ActivityList;
  transport: ControlTransport;
  labels: ControlLabels;
  now?: () => Date;
  /** Tells the card what the changes hold now, so a switch away and back shows it, not the first read. */
  onData?: (data: ChangesList) => void;
  /** The host's chat function; the empty state's example sentence sends through it. Absent: the example is text. */
  sendMessage?: (text: string) => Promise<boolean>;
  /** Called once an undo is saved, with a generic sentence for the host model. */
  onModelContext?: (summary: string) => void;
  /** Whether "Show all" is open; the card keeps it across tabs. */
  expanded?: boolean;
  onExpandedChange?: (next: boolean) => void;
}) {
  const [list, setList] = useState(initial);
  // A new `initial` is a fresh read from the card (a refresh): it replaces the data and keeps
  // what the view holds on screen (busy, notices, focus).
  const [seenInitial, setSeenInitial] = useState(initial);
  if (initial !== seenInitial) {
    setSeenInitial(initial);
    setList(initial);
  }
  useEffect(() => {
    if (list) onData?.(list);
  }, [list, onData]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | undefined>();
  const pending = useRef<PendingKey | undefined>(undefined);
  const rootRef = useRef<HTMLDivElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  /** The row a write was on. Focus moves there once the write is over, since its button may be gone. */
  const focusIndex = useRef<number | null>(null);

  useEffect(() => {
    const index = focusIndex.current;
    const root = rootRef.current;
    if (busy !== null || index === null || !root) return;
    focusIndex.current = null;
    const active = document.activeElement;
    if (
      active?.isConnected &&
      active !== document.body &&
      !root.contains(active)
    )
      return;
    focusRowNear(root, index, noticeRef.current);
  }, [busy, list]);

  const rows = [
    ...(list?.changes ?? []).map((change) => ({
      key: `c:${rowKey(change)}`,
      at: change.occurred_at,
      change,
      entry: undefined,
    })),
    ...(activity?.items ?? []).map((entry) => ({
      key: `a:${entry.id}`,
      at: entry.occurred_at,
      change: undefined,
      entry,
    })),
  ].sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));

  async function reload() {
    try {
      setList(await transport.changes());
    } catch {
      // Keep the old rows; the notice already told the owner what happened.
    }
  }

  async function undo(change: ChangeRecord) {
    if (busy) return;
    const rowId = `c:${rowKey(change)}`;
    focusIndex.current = rows.findIndex((row) => row.key === rowId);
    setBusy(rowId);
    setNotice(undefined);
    pending.current = keyFor(
      pending.current,
      `${change.kind}:${change.id}:${change.version}:${change.action}`,
    );
    try {
      await transport.undoPurchase(change, pending.current.key);
      pending.current = undefined;
      onModelContext?.(labels.modelNote.undone);
      setNotice({
        tone: "ok",
        text:
          change.action === "purchased"
            ? labels.undoneUnbought(change.title)
            : labels.undoneBought(change.title),
      });
      await reload();
    } catch (error) {
      const failure = writeFailure(error);
      if (failure === "conflict" || failure === "not_found") {
        pending.current = undefined;
        setNotice({
          tone: "error",
          text: labels.undoConflict(change.title),
        });
        await reload();
      } else {
        setNotice({
          tone: "error",
          text:
            failure === "forbidden" ? labels.undoForbidden : labels.undoFailed,
        });
      }
    } finally {
      setBusy(null);
    }
  }

  /** The same write as the trash card: restore_from_trash with the version this row shows. */
  async function restore(change: ChangeRecord) {
    if (busy) return;
    const rowId = `c:${rowKey(change)}`;
    focusIndex.current = rows.findIndex((row) => row.key === rowId);
    setBusy(rowId);
    setNotice(undefined);
    pending.current = keyFor(
      pending.current,
      `${change.kind}:${change.id}:${change.version}`,
    );
    // Restore is offered only for a trashed record, so its kind is one of the trash kinds even
    // though list_recent_changes types `kind` as a plain string.
    const item: TrashItem = {
      kind: change.kind as TrashItem["kind"],
      id: change.id,
      label: change.title,
      trashed_at: null,
      version: change.version,
    };
    try {
      await transport.restore(item, pending.current.key);
      pending.current = undefined;
      onModelContext?.(labels.modelNote.restored);
      setNotice({ tone: "ok", text: labels.restored(change.title) });
      await reload();
    } catch (error) {
      const failure = writeFailure(error);
      if (failure === "conflict" || failure === "not_found") {
        pending.current = undefined;
        setNotice({
          tone: "error",
          text:
            failure === "conflict"
              ? labels.restoreConflict(change.title)
              : labels.restoreGone,
        });
        await reload();
      } else {
        setNotice({
          tone: "error",
          text:
            failure === "forbidden"
              ? labels.restoreForbidden
              : labels.restoreFailed,
        });
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="control-view" ref={rootRef}>
      <h2 className="control-sr-only">{labels.views.history}</h2>
      {/* The tab's one meta line, as the view's first content. */}
      {rows.length > 0 ? (
        <p className="control-meta">{labels.historyMeta}</p>
      ) : null}
      {notice ? (
        <div ref={noticeRef} tabIndex={-1}>
          <NoticeLine notice={notice} />
        </div>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState
          title={labels.historyEmpty}
          hint={labels.historyEmptyHint}
          ask={{
            locale: labels.locale,
            example: labels.historyAskExample,
            ...(sendMessage
              ? { onSend: () => void sendMessage(labels.historyAskExample) }
              : {}),
          }}
        />
      ) : (
        <RowList
          items={rows}
          keyOf={(row) => row.key}
          label={labels.views.history}
          showAll={labels.showAll}
          showFewer={labels.showFewer}
          expanded={expanded}
          onExpandedChange={onExpandedChange}
          renderRow={({ change, entry, at }) => {
            const when = whenText(at, now(), labels.locale);
            if (entry) {
              // "applied" is the normal case, so only the other states are named.
              const parts = [
                sourceName(labels, entry.source),
                entry.state === "applied" ? "" : stateName(labels, entry.state),
                when,
              ];
              return (
                <ControlRow
                  primary={
                    entry.summary.trim() ||
                    kindName(labels, entry.aggregate_type)
                  }
                  secondary={parts.filter(Boolean).join(" · ")}
                />
              );
            }
            const parts = [
              kindName(labels, change.kind),
              actionName(labels, change.action),
              actorName(labels, change.actor),
              when,
            ];
            if (change.state === "trashed" && change.action !== "trashed")
              parts.push(labels.nowTrashed);
            const isBusy = busy === `c:${rowKey(change)}`;
            return (
              <ControlRow
                primary={change.title}
                secondary={parts.filter(Boolean).join(" · ")}
                action={
                  canUndo(change) ? (
                    <button
                      type="button"
                      className="sk-btn--secondary sk-btn--compact control-row-btn"
                      aria-label={labels.undoLabel(labels.undo, change.title)}
                      disabled={busy !== null}
                      onClick={() => void undo(change)}
                    >
                      {isBusy ? labels.undoing : labels.undo}
                    </button>
                  ) : change.state === "trashed" ? (
                    <button
                      type="button"
                      className="sk-btn--secondary sk-btn--compact control-row-btn"
                      aria-label={labels.restoreLabel(change.title)}
                      disabled={busy !== null}
                      onClick={() => void restore(change)}
                    >
                      {isBusy ? labels.restoring : labels.restore}
                    </button>
                  ) : undefined
                }
              />
            );
          }}
        />
      )}
      {activity && activity.next_cursor !== null ? (
        <p className="control-note">{labels.activityTruncated}</p>
      ) : null}
    </div>
  );
}

/**
 * Moves focus to the button of the row at `index` (the row that took its place, or the one before
 * when it was last). A row without a button is skipped; with no button left, focus goes to `fallback`.
 */
function focusRowNear(
  root: HTMLElement,
  index: number,
  fallback: HTMLElement | null,
) {
  const rows = Array.from(
    root.querySelectorAll<HTMLLIElement>("li.control-row"),
  );
  const start = Math.max(0, index);
  const order = [...rows.slice(start), ...rows.slice(0, start).reverse()];
  for (const row of order) {
    const button = row.querySelector("button");
    if (button) {
      button.focus();
      return;
    }
  }
  fallback?.focus();
}

/** A record can appear in several changes, so a row is identified by its record and its time. */
function rowKey(change: ChangeRecord): string {
  return `${change.kind}:${change.id}:${change.occurred_at}:${change.action}`;
}
