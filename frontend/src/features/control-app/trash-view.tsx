import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { EmptyState } from "../mcp-apps/ui/states";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import type { RoomTarget } from "../mcp-apps/room-types";
import {
  actionName,
  kindName,
  trashedWhen,
  type ControlLabels,
} from "./labels";
import { ConfirmErase } from "./confirm-erase";
import { ControlRow, NoticeLine, RowList, type Notice } from "./control-parts";
import { focusRowNear } from "./focus-row";
import { openTargetOf } from "./open-target";
import {
  writeFailure,
  type TrashItem,
  type TrashList,
  type TrashTransport,
} from "./transport";
import { useReceipts } from "./use-receipts";
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
 * A restore or a delete that is saved leaves the row on its place and its meta line says what happened (the kind and the
 * word, a status, no buttons) for RESTORED_MS, then the row goes. When the room can open the record, the open link stands at
 * the end of the row meanwhile. It has no Undo: no tool puts an item back in the trash. A failure stays in its row
 * until the next action.
 */
export function TrashView({
  initial,
  transport,
  labels,
  now = () => new Date(),
  onData,
  onModelContext,
  onOpen,
  full = false,
  expanded,
  onExpandedChange,
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
  /** The full view lists every row read so far; the inline card lists three behind "Show all". */
  full?: boolean;
  /** Whether "Show all" is open; the card keeps it across tabs. */
  expanded?: boolean;
  onExpandedChange?: (next: boolean) => void;
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
  // Restored rows: gone from the list (and from the card's data) at once, shown on their place until the receipt ends.
  // `index` is how many rows of the list stood before the item.
  const [receipts, showReceipt] = useReceipts<Receipt>();
  // The question asked before anything is removed for good: one Task, or the whole trash.
  const [confirming, setConfirming] = useState<Confirming>(null);
  // The list with the restored rows put back on their places, for as long as their receipts stand.
  const shown = withReceiptRows(list.items, receipts);
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
    focusIndex.current = shown.findIndex((row) => row.id === item.id);
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
      showReceipt(item.id, {
        item,
        index: Math.max(
          0,
          list.items.findIndex((row) => row.id === item.id),
        ),
        how: "restored",
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
          tone: "error",
          text:
            failure === "conflict"
              ? labels.restoreConflict(item.label)
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
    focusIndex.current = shown.findIndex((row) => row.id === item.id);
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
      showReceipt(item.id, {
        item,
        index: Math.max(
          0,
          list.items.findIndex((row) => row.id === item.id),
        ),
        how: "erased",
      });
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
          tone: "error",
          text:
            failure === "conflict" ? labels.eraseConflict : labels.restoreGone,
        });
        await reload();
      } else {
        setNotice({
          tone: "error",
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
      setNotice({
        tone: "ok",
        text: labels.emptyDone(result.removed, result.kept),
      });
    } catch (error) {
      setConfirming(null);
      const forbidden = writeFailure(error) === "forbidden";
      setNotice({
        tone: "error",
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
    notice?.tone === "error" &&
    failedRow !== null &&
    items.some((row) => row.id === failedRow);
  return (
    <div className="control-view" ref={rootRef}>
      {/* The `trash` tab names the view (designsystem §5): the heading is for assistive technology only, and is
          where focus rests when the "Restored" line it was on goes away. With rows, the view's first content is one meta
          line (the deleted count and the restore note). */}
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
      {shown.length === 0 ? (
        <EmptyState title={labels.trashEmpty} hint={labels.trashEmptyHint} />
      ) : (
        <RowList
          items={shown}
          keyOf={(item) => item.id}
          label={labels.trashTitle}
          isReceipt={(item) => receipts.has(item.id)}
          showAll={(count) => labels.showAll(count, list.has_more)}
          showFewer={labels.showFewer}
          full={full}
          expanded={expanded}
          onExpandedChange={onExpandedChange}
          renderRow={(item) => {
            const title = item.label ?? labels.hiddenTitle;
            const when = whenText(item.trashed_at, now(), labels.locale);
            const target = onOpen && openTargetOf(item);
            const receipt = receipts.get(item.id);
            const erasable = canErase && item.kind === "task";
            return (
              <ControlRow
                primary={title}
                secondary={`${kindName(labels, item.kind)} · ${trashedWhen(labels, when, item.kind)}`}
                receipt={
                  receipt
                    ? `${kindName(labels, item.kind)} · ${receipt.how === "erased" ? labels.erased : actionName(labels, "restored", item.kind)}`
                    : undefined
                }
                receiptAction={
                  target && receipt?.how !== "erased" ? (
                    <button
                      type="button"
                      className="sk-btn--open"
                      aria-label={labels.openLabel(title)}
                      onClick={() => onOpen(target)}
                    >
                      {labels.open}
                      <ChevronRightIcon />
                    </button>
                  ) : undefined
                }
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
                      yes={busy === item.id ? labels.erasing : labels.eraseYes}
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
      {canErase && items.some((row) => row.kind !== "task") ? (
        <p className="control-note">{labels.eraseHelp}</p>
      ) : null}
      {list.has_more && list.next_cursor ? (
        <div className="control-page-more">
          {more === "failed" ? (
            <NoticeLine
              locale={labels.locale}
              notice={{
                tone: "error",
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
    </div>
  );
}

/** A row kept on its place for a moment after a write: what it was and how many rows stood before it. */
type Receipt = { item: TrashItem; index: number; how: "restored" | "erased" };

/** The question that stands open: one Task to delete for good, or all of them. */
type Confirming = { what: "task"; id: string } | { what: "all" } | null;

/** `busy` while the whole trash is being emptied (no row has this id). */
const EMPTYING = "empty";

/** `items` with each restored row back where it stood: after the `index` rows that stood before it. */
function withReceiptRows(
  items: readonly TrashItem[],
  receipts: ReadonlyMap<string, Receipt>,
): TrashItem[] {
  if (receipts.size === 0) return [...items];
  const restored = [...receipts.values()].sort((a, b) => a.index - b.index);
  const at = (position: number) =>
    restored
      .filter(({ index }) =>
        position === items.length ? index >= position : index === position,
      )
      .map(({ item }) => item);
  return [
    ...items.flatMap((row, position) => [...at(position), row]),
    ...at(items.length),
  ];
}
