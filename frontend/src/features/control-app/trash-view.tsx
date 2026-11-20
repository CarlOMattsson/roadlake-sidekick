import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { EmptyState } from "../mcp-apps/ui/states";
import { ReceiptBar, useReceipt } from "../mcp-apps/ui/receipt";
import type { RoomTarget } from "../mcp-apps/room-types";
import {
  receiptText,
  kindName,
  trashedWhen,
  type ControlLabels,
} from "./labels";
import { ConfirmErase } from "./confirm-erase";
import {
  ControlRow,
  INLINE_ROWS,
  NoticeLine,
  RowList,
  ViewOpenLink,
  rowLimit,
  type Notice,
} from "./control-parts";
import { focusRowNear } from "./focus-row";
import { openTargetOf } from "./open-target";
import {
  writeFailure,
  type TrashItem,
  type TrashList,
  type TrashTransport,
} from "./transport";
import { useReportedData } from "./use-reported-data";
import { whenText } from "./when";

/**
 * Trash as an inline card. Each row has a visible Restore button (restore_from_trash with the
 * version the list showed). A stale version or a vanished item reads the list again and says so.
 * Where the transport has `erase` and `empty` (the phone; Claude has neither) a Task row also has "Delete permanently",
 * and the view has "Empty the trash". Each asks first, inline, naming what goes and that it cannot be undone, and calls
 * the transport only after the owner chose the red button. A Journal entry or a Shopping item never gets the button:
 * the server cannot remove them, only restore them.
 *
 * A restore or a delete that is saved takes the row out of the list at once and says what happened in the receipt bar
 * ("Återställd: Mjölk", "Raderad för gott: Pitchen"); a restored record the room can open has "Visa" in the bar. It has
 * no Undo: no tool puts an item back in the trash. A failure stays in its row until the next action.
 *
 * The inline card lists three rows; its one main link, "Öppna Borttaget › · 4 till", opens the full view.
 */
export function TrashView({
  initial,
  transport,
  labels,
  now = () => new Date(),
  onData,
  onModelContext,
  onOpen,
  onOpenFull,
  full = false,
}: {
  initial: TrashList;
  transport: TrashTransport;
  labels: ControlLabels;
  now?: () => Date;
  /** Tells the card what this view holds now, so a switch away and back shows it, not the first read. */
  onData?: (data: TrashList) => void;
  /** Called once a restore is saved, with a generic sentence for the host model. */
  onModelContext?: (summary: string) => void;
  /** Opens a restored record in its room; absent: the receipt offers no link. */
  onOpen?: (target: RoomTarget) => void;
  /** Opens this view in fullscreen (the inline card's main link); absent: the card has no link and lists every row. */
  onOpenFull?: () => void;
  /** The full view lists every row read so far; the inline card lists three behind its open link. */
  full?: boolean;
}) {
  const [more, setMore] = useState<"idle" | "busy" | "failed">("idle");
  // Counts the reads that replace the list, so a page that was asked for before one lands on nothing.
  const readTicket = useRef(0);
  const [list, change] = useReportedData(initial, onData, () => {
    setMore("idle");
    readTicket.current++;
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | undefined>();
  // The row a failed restore was on: its notice stands in that row, where the owner is looking, not at the top of the list.
  const [failedRow, setFailedRow] = useState<string | null>(null);
  // What a saved restore or delete did, in the bar at the foot of the view; the row itself is gone from the list at once.
  const receipt = useReceipt();
  // The question asked before anything is removed for good: one Task, or the whole trash.
  const [confirming, setConfirming] = useState<Confirming>(null);
  const pending = useRef<PendingKey | undefined>(undefined);
  const rootRef = useRef<HTMLDivElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const eraseButtons = useRef(new Map<string, HTMLButtonElement>());
  const emptyButton = useRef<HTMLButtonElement>(null);
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
    focusRowNear(root, index, noticeRef.current ?? headingRef.current);
  }, [busy, list]);

  /** Closes the question and gives the focus back to the button that asked it. */
  function cancelConfirm() {
    const asked = confirming;
    setConfirming(null);
    queueMicrotask(() =>
      (asked?.what === "task"
        ? eraseButtons.current.get(asked.id)
        : emptyButton.current
      )?.focus(),
    );
  }

  async function reload() {
    readTicket.current++;
    setMore("idle");
    try {
      const fresh = await transport.trash();
      change(() => fresh);
    } catch {
      // Keep the old rows; the notice already told the owner what happened.
    }
  }

  /** Appends the page after the last one read; a row the list already holds is not shown twice. */
  async function loadMore() {
    if (!list.next_cursor || more === "busy") return;
    const ticket = readTicket.current;
    setMore("busy");
    try {
      const page = await transport.trash(list.next_cursor);
      if (ticket !== readTicket.current) return;
      change((current) => {
        const seen = new Set(current.items.map((row) => row.id));
        return {
          items: [
            ...current.items,
            ...page.items.filter((row) => !seen.has(row.id)),
          ],
          has_more: page.has_more,
          next_cursor: page.next_cursor,
        };
      });
      setMore("idle");
    } catch {
      if (ticket === readTicket.current) setMore("failed");
    }
  }

  async function restore(item: TrashItem) {
    if (busy) return;
    focusIndex.current = list.items.findIndex((row) => row.id === item.id);
    setBusy(item.id);
    setNotice(undefined);
    setFailedRow(null);
    pending.current = keyFor(
      pending.current,
      `${item.kind}:${item.id}:${item.version}`,
    );
    try {
      await transport.restore(item, pending.current.key);
      pending.current = undefined;
      onModelContext?.(labels.modelNote.restored);
      const target = onOpen && openTargetOf(item);
      receipt.show({
        message: receiptText(labels.restored, item.label),
        ...(target
          ? { action: { label: labels.show, onClick: () => onOpen?.(target) } }
          : {}),
      });
      change((current) => ({
        ...current,
        items: current.items.filter((row) => row.id !== item.id),
      }));
    } catch (error) {
      setFailedRow(item.id);
      const failure = writeFailure(error);
      if (failure === "conflict" || failure === "not_found") {
        pending.current = undefined;
        setNotice({
          text:
            failure === "conflict"
              ? labels.restoreConflict(item.label)
              : labels.restoreGone,
        });
        await reload();
      } else {
        setNotice({
          text:
            failure === "forbidden"
              ? labels.restoreForbidden
              : labels.restoreFailed,
          retry: failure === "forbidden" ? undefined : () => void restore(item),
        });
      }
    } finally {
      setBusy(null);
    }
  }

  /** Removes one Task for good, after the owner said yes in the row's question. */
  async function erase(item: TrashItem) {
    if (busy || !transport.erase) return;
    focusIndex.current = list.items.findIndex((row) => row.id === item.id);
    setBusy(item.id);
    setNotice(undefined);
    setFailedRow(null);
    pending.current = keyFor(
      pending.current,
      `erase:${item.id}:${item.version}`,
    );
    try {
      await transport.erase(item, pending.current.key);
      pending.current = undefined;
      setConfirming(null);
      receipt.show({ message: receiptText(labels.erased, item.label) });
      change((current) => ({
        ...current,
        items: current.items.filter((row) => row.id !== item.id),
      }));
    } catch (error) {
      setConfirming(null);
      setFailedRow(item.id);
      const failure = writeFailure(error);
      if (failure === "conflict" || failure === "not_found") {
        pending.current = undefined;
        setNotice({
          text:
            failure === "conflict" ? labels.eraseConflict : labels.restoreGone,
        });
        await reload();
      } else {
        setNotice({
          text:
            failure === "forbidden"
              ? labels.eraseForbidden
              : labels.eraseFailed,
          retry: failure === "forbidden" ? undefined : () => void erase(item),
        });
      }
    } finally {
      setBusy(null);
    }
  }

  /** Removes every Task in the trash for good, after the owner said yes; then reads the list again and says what went. */
  async function emptyAll(tasks: readonly TrashItem[]) {
    if (busy || !transport.empty) return;
    setBusy(EMPTYING);
    setNotice(undefined);
    setFailedRow(null);
    pending.current = keyFor(
      pending.current,
      `empty:${tasks.map((task) => `${task.id}:${task.version}`).join(",")}`,
    );
    try {
      const result = await transport.empty(pending.current.key);
      pending.current = undefined;
      setConfirming(null);
      await reload();
      receipt.show({ message: labels.emptyDone(result.removed, result.kept) });
    } catch (error) {
      setConfirming(null);
      const forbidden = writeFailure(error) === "forbidden";
      setNotice({
        text: forbidden ? labels.eraseForbidden : labels.emptyFailed,
        retry: forbidden ? undefined : () => void emptyAll(tasks),
      });
    } finally {
      setBusy(null);
    }
  }

  const items = list.items;
  const tasks = items.filter((row) => row.kind === "task");
  const canErase = transport.erase !== undefined;
  // A failure stays at the top only when its row is gone (the list was read again and no longer holds it).
  const failureInRow =
    notice !== undefined &&
    failedRow !== null &&
    items.some((row) => row.id === failedRow);
  const hidden = Math.max(0, items.length - INLINE_ROWS);
  // The foot of the list (the next page, the note on what cannot be deleted) belongs to the full view; the inline card
  // leaves what it does not list behind its open link.
  const showFoot = full || !onOpenFull || hidden === 0;
  return (
    <>
      <div className="control-view" ref={rootRef}>
        {/* The `trash` tab names the view (designsystem §5): the heading is for assistive technology only, and is
          where focus rests when the row it was on is gone. With rows, the view's first content is one meta line (the
          deleted count). */}
        <h2 ref={headingRef} tabIndex={-1} className="control-sr-only">
          {labels.trashTitle}
        </h2>
        {items.length > 0 ? (
          <p className="control-meta">
            {labels.trashMeta(items.length, list.has_more)}
          </p>
        ) : null}
        {transport.empty && tasks.length > 0 ? (
          <div className="control-empty-trash">
            <button
              ref={emptyButton}
              type="button"
              className="sk-btn--secondary sk-btn--compact control-erase-btn"
              disabled={busy !== null || confirming !== null}
              onClick={() => setConfirming({ what: "all" })}
            >
              {labels.emptyTrash}
            </button>
            {confirming?.what === "all" ? (
              <ConfirmErase
                question={labels.emptyQuestion(tasks.length, list.has_more)}
                yes={busy === EMPTYING ? labels.erasing : labels.eraseYes}
                no={labels.eraseNo}
                busy={busy !== null}
                onYes={() => void emptyAll(tasks)}
                onNo={cancelConfirm}
              />
            ) : null}
          </div>
        ) : null}
        {notice && !failureInRow ? (
          <div ref={noticeRef} tabIndex={-1}>
            <NoticeLine notice={notice} locale={labels.locale} />
          </div>
        ) : null}
        {items.length === 0 ? (
          <EmptyState title={labels.trashEmpty} hint={labels.trashEmptyHint} />
        ) : (
          <RowList
            items={items}
            keyOf={(item) => item.id}
            label={labels.trashTitle}
            limit={rowLimit(full, onOpenFull)}
            renderRow={(item) => {
              const title = item.label ?? labels.hiddenTitle;
              const when = whenText(item.trashed_at, now(), labels.locale);
              const erasable = canErase && item.kind === "task";
              return (
                <ControlRow
                  primary={title}
                  secondary={`${kindName(labels, item.kind)} · ${trashedWhen(labels, when, item.kind)}`}
                  stackedAction={erasable}
                  action={
                    <>
                      <button
                        type="button"
                        className="sk-btn--secondary sk-btn--compact control-row-btn"
                        aria-label={labels.restoreLabel(title)}
                        disabled={busy !== null || confirming !== null}
                        onClick={() => void restore(item)}
                      >
                        {busy === item.id && confirming === null
                          ? labels.restoring
                          : labels.restore}
                      </button>
                      {erasable ? (
                        <button
                          type="button"
                          className="sk-btn--secondary sk-btn--compact control-row-btn control-erase-btn"
                          aria-label={labels.eraseLabel(title)}
                          disabled={busy !== null || confirming !== null}
                          ref={(node) => {
                            if (node) eraseButtons.current.set(item.id, node);
                            else eraseButtons.current.delete(item.id);
                          }}
                          onClick={() =>
                            setConfirming({ what: "task", id: item.id })
                          }
                        >
                          {labels.erase}
                        </button>
                      ) : null}
                    </>
                  }
                  below={
                    confirming?.what === "task" && confirming.id === item.id ? (
                      <ConfirmErase
                        question={labels.eraseQuestion(item.label)}
                        yes={
                          busy === item.id ? labels.erasing : labels.eraseYes
                        }
                        no={labels.eraseNo}
                        busy={busy !== null}
                        onYes={() => void erase(item)}
                        onNo={cancelConfirm}
                      />
                    ) : failureInRow && failedRow === item.id ? (
                      <NoticeLine notice={notice} locale={labels.locale} />
                    ) : undefined
                  }
                />
              );
            }}
          />
        )}
        {showFoot && canErase && items.some((row) => row.kind !== "task") ? (
          <p className="control-note">{labels.eraseHelp}</p>
        ) : null}
        {showFoot && list.has_more && list.next_cursor ? (
          <div className="control-page-more">
            {more === "failed" ? (
              <NoticeLine
                locale={labels.locale}
                notice={{
                  text: labels.trashMoreFailed,
                  retry: () => void loadMore(),
                }}
              />
            ) : null}
            <button
              type="button"
              className="control-more sk-more"
              disabled={more === "busy"}
              onClick={() => void loadMore()}
            >
              {more === "busy" ? labels.loading : labels.trashMore}
            </button>
          </div>
        ) : null}
        <ViewOpenLink
          labels={labels}
          view="trash"
          hidden={hidden}
          moreRead={list.has_more}
          full={full}
          onOpenFull={onOpenFull}
        />
      </div>
      <ReceiptBar receipt={receipt} />
    </>
  );
}

/** The question that stands open: one Task to delete for good, or all of them. */
type Confirming = { what: "task"; id: string } | { what: "all" } | null;

/** `busy` while the whole trash is being emptied (no row has this id). */
const EMPTYING = "empty";
