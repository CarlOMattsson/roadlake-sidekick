import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { EmptyState } from "../mcp-apps/ui/states";
import { kindName, trashedWhen, type ControlLabels } from "./labels";
import { ControlRow, NoticeLine, RowList, type Notice } from "./control-parts";
import { focusRowNear } from "./focus-row";
import {
  writeFailure,
  type ControlTransport,
  type TrashItem,
  type TrashList,
} from "./transport";
import { useReceipts } from "./use-receipts";
import { useReportedData } from "./use-reported-data";
import { whenText } from "./when";

/**
 * Trash as an inline card. Each row has a visible Restore button (restore_from_trash with the
 * version the list showed). A stale version or a vanished item reads the list again and says so.
 * There is no way to empty the trash or delete anything for good from here.
 *
 * A restore that is saved leaves the row on its place and its meta line says "Återställd" (a status, no button) for
 * RESTORED_MS, then the row goes. It has no Undo: no tool puts an item back in the trash. A failure stays in its row
 * until the next action.
 */
export function TrashView({
  initial,
  transport,
  labels,
  now = () => new Date(),
  onData,
  onModelContext,
  full = false,
  expanded,
  onExpandedChange,
}: {
  initial: TrashList;
  transport: ControlTransport;
  labels: ControlLabels;
  now?: () => Date;
  /** Tells the card what this view holds now, so a switch away and back shows it, not the first read. */
  onData?: (data: TrashList) => void;
  /** Called once a restore is saved, with a generic sentence for the host model. */
  onModelContext?: (summary: string) => void;
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
  const [receipts, showReceipt] = useReceipts<{
    item: TrashItem;
    index: number;
  }>();
  // The list with the restored rows put back on their places, for as long as their receipts stand.
  const shown = withReceiptRows(list.items, receipts);
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
    focusRowNear(root, index, noticeRef.current ?? headingRef.current);
  }, [busy, list]);

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

  const items = list.items;
  // A failure stays at the top only when its row is gone (the list was read again and no longer holds it).
  const failureInRow =
    notice?.tone === "error" &&
    failedRow !== null &&
    items.some((row) => row.id === failedRow);
  return (
    <div className="control-view" ref={rootRef}>
      {/* The tab "Borttaget" names the view (designsystem §5): the heading is for assistive technology only, and is
          where focus rests when the "Restored" line it was on goes away. With rows, the view's first content is one meta
          line, "3 borttagna · kan återställas". */}
      <h2 ref={headingRef} tabIndex={-1} className="control-sr-only">
        {labels.trashTitle}
      </h2>
      {items.length > 0 ? (
        <p className="control-meta">
          {labels.trashMeta(items.length, list.has_more)}
        </p>
      ) : null}
      {notice?.tone === "error" && !failureInRow ? (
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
          showAll={() => labels.showAll(items.length, list.has_more)}
          showFewer={labels.showFewer}
          full={full}
          expanded={expanded}
          onExpandedChange={onExpandedChange}
          renderRow={(item) => {
            const title = item.label ?? labels.hiddenTitle;
            const when = whenText(item.trashed_at, now(), labels.locale);
            return (
              <ControlRow
                primary={title}
                secondary={`${kindName(labels, item.kind)} · ${trashedWhen(labels, when, item.kind)}`}
                receipt={receipts.has(item.id) ? labels.restored : undefined}
                action={
                  <button
                    type="button"
                    className="sk-btn--secondary sk-btn--compact control-row-btn"
                    aria-label={labels.restoreLabel(title)}
                    disabled={busy !== null}
                    onClick={() => void restore(item)}
                  >
                    {busy === item.id ? labels.restoring : labels.restore}
                  </button>
                }
                below={
                  failureInRow && failedRow === item.id ? (
                    <NoticeLine notice={notice} locale={labels.locale} />
                  ) : undefined
                }
              />
            );
          }}
        />
      )}
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

/** `items` with each restored row back where it stood: after the `index` rows that stood before it. */
function withReceiptRows(
  items: readonly TrashItem[],
  receipts: ReadonlyMap<string, { item: TrashItem; index: number }>,
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
