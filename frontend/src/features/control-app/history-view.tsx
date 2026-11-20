import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { EmptyState } from "../mcp-apps/ui/states";
import { ReceiptBar, useReceipt } from "../mcp-apps/ui/receipt";
import {
  actionName,
  actorName,
  kindName,
  receiptText,
  sourceName,
  stateName,
  type ControlLabels,
} from "./labels";
import {
  ControlRow,
  INLINE_ROWS,
  NoticeLine,
  RowList,
  ViewOpenLink,
  rowLimit,
  type Notice,
} from "./control-parts";
import { activityText, withoutRepeatedActivity } from "./activity-rows";
import { focusRowNear } from "./focus-row";
import {
  canUndo,
  writeFailure,
  type ActivityList,
  type ChangeRecord,
  type ChangesList,
  type ControlTransport,
  type TrashItem,
} from "./transport";
import { useReportedData } from "./use-reported-data";
import { whenText } from "./when";

/**
 * History as one list, newest first: the changes (Undo when the server named an existing tool for it,
 * set_shopping_item_purchased; Restore when the record is in the trash, the same restore_from_trash call as
 * the trash card) and the assistant's activity (read only). A row without an action has nothing at the end.
 * Either part may be missing (its read failed or has not come yet); the list shows what there is. A saved Undo or Restore
 * says what happened in the receipt bar; a failure stays in its row.
 *
 * The inline card lists three rows; its one main link, "Öppna Historik › · 4 till", opens the full view.
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
  onOpenFull,
  full = false,
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
  /** Opens this view in fullscreen (the inline card's main link); absent: the card has no link and lists every row. */
  onOpenFull?: () => void;
  /** The full view lists every row read; the inline card lists three behind its open link. */
  full?: boolean;
}) {
  const [list, change] = useReportedData(initial, onData);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | undefined>();
  // The row a failed write was on: its notice stands in that row, where the owner is looking, not at the top of the list.
  const [failedRow, setFailedRow] = useState<string | null>(null);
  // What a saved Undo or Restore did, in the bar at the foot of the view.
  const receipt = useReceipt();
  const pending = useRef<PendingKey | undefined>(undefined);
  const rootRef = useRef<HTMLDivElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
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
    // A failure that can be repeated stands in its row: focus goes to its "Try again".
    const retry = root.querySelector<HTMLElement>(
      "li.control-row [role='alert'] button",
    );
    if (retry) {
      retry.focus();
      return;
    }
    focusRowNear(root, index, noticeRef.current ?? headingRef.current);
  }, [busy, list]);

  const changes = list?.changes ?? [];
  const rows = [
    ...changes.map((change) => ({
      key: `c:${rowKey(change)}`,
      at: change.occurred_at,
      change,
      entry: undefined,
    })),
    ...withoutRepeatedActivity(changes, activity?.items ?? []).map((entry) => ({
      key: `a:${entry.id}`,
      at: entry.occurred_at,
      change: undefined,
      entry,
    })),
  ].sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));

  async function reload() {
    try {
      const fresh = await transport.changes();
      change(() => fresh);
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
    setFailedRow(null);
    pending.current = keyFor(
      pending.current,
      `${change.kind}:${change.id}:${change.version}:${change.action}`,
    );
    try {
      await transport.undoPurchase(change, pending.current.key);
      pending.current = undefined;
      onModelContext?.(labels.modelNote.undone);
      receipt.show({
        message: receiptText(
          change.action === "purchased"
            ? labels.undoneUnbought
            : labels.undoneBought,
          change.title,
        ),
      });
      await reload();
    } catch (error) {
      setFailedRow(rowId);
      const failure = writeFailure(error);
      if (failure === "conflict" || failure === "not_found") {
        pending.current = undefined;
        setNotice({
          text: labels.undoConflict(change.title),
        });
        await reload();
      } else {
        setNotice({
          text:
            failure === "forbidden"
              ? labels.undoForbidden
              : labels.undoFailed(change.title),
          retry: failure === "forbidden" ? undefined : () => void undo(change),
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
    setFailedRow(null);
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
      receipt.show({ message: receiptText(labels.restored, change.title) });
      await reload();
    } catch (error) {
      setFailedRow(rowId);
      const failure = writeFailure(error);
      if (failure === "conflict" || failure === "not_found") {
        pending.current = undefined;
        setNotice({
          text:
            failure === "conflict"
              ? labels.restoreConflict(change.title)
              : labels.restoreGone,
        });
        await reload();
      } else {
        setNotice({
          text:
            failure === "forbidden"
              ? labels.restoreForbidden
              : labels.restoreFailed,
          retry:
            failure === "forbidden" ? undefined : () => void restore(change),
        });
      }
    } finally {
      setBusy(null);
    }
  }

  // A failure stays at the top only when its row is gone (the list was read again and no longer holds it).
  const failureInRow =
    notice !== undefined &&
    failedRow !== null &&
    rows.some((row) => row.key === failedRow);
  const hidden = Math.max(0, rows.length - INLINE_ROWS);
  return (
    <>
      <div className="control-view" ref={rootRef}>
        {/* Where focus rests when the row it was on has no button left (the list was read again without it). */}
        <h2 ref={headingRef} tabIndex={-1} className="control-sr-only">
          {labels.views.history}
        </h2>
        {/* The tab's one meta line, as the view's first content. */}
        {rows.length > 0 ? (
          <p className="control-meta">{labels.historyMeta}</p>
        ) : null}
        {notice && !failureInRow ? (
          <div ref={noticeRef} tabIndex={-1}>
            <NoticeLine notice={notice} locale={labels.locale} />
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
            wrapMeta
            limit={rowLimit(full, onOpenFull)}
            renderRow={({ key, change, entry, at }) => {
              const when = whenText(at, now(), labels.locale);
              if (entry) {
                // "applied" is the normal case, so only the other states are named.
                const parts = [
                  sourceName(labels, entry.source),
                  entry.state === "applied"
                    ? ""
                    : stateName(labels, entry.state),
                  when,
                ];
                return (
                  <ControlRow
                    primary={
                      activityText(labels, entry) ||
                      kindName(labels, entry.aggregate_type)
                    }
                    secondary={parts.filter(Boolean).join(" · ")}
                  />
                );
              }
              const parts = [
                kindName(labels, change.kind),
                actionName(labels, change.action, change.kind),
                actorName(labels, change.actor),
                when,
              ];
              if (change.state === "trashed" && change.action !== "trashed")
                parts.push(labels.nowTrashed);
              const isBusy = busy === key;
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
                  below={
                    failureInRow && failedRow === key ? (
                      <NoticeLine notice={notice} locale={labels.locale} />
                    ) : undefined
                  }
                />
              );
            }}
          />
        )}
        {(full || !onOpenFull || hidden === 0) &&
        activity &&
        activity.next_cursor !== null ? (
          <p className="control-note">{labels.activityTruncated}</p>
        ) : null}
        <ViewOpenLink
          labels={labels}
          view="history"
          hidden={hidden}
          full={full}
          onOpenFull={onOpenFull}
        />
      </div>
      <ReceiptBar receipt={receipt} />
    </>
  );
}

/** A record can appear in several changes, so a row is identified by its record and its time. */
function rowKey(change: ChangeRecord): string {
  return `${change.kind}:${change.id}:${change.occurred_at}:${change.action}`;
}
