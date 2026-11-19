import { useCallback, useState } from "react";
import type { ShoppingItem, ShoppingTransport } from "../transport";
import type { ShoppingLabels } from "../labels";
import type { Receipt } from "./receipts";
import type { ShoppingRead } from "./use-shopping-read";
import type { ShoppingWrites } from "./use-shopping-writes";

/** An item that went to the trash and can still be taken back from its receipt row. */
export type TrashedItem = {
  item: ShoppingItem;
  /** The trash record's version, which the restore needs. */
  version: number;
};

type Params = {
  transport: ShoppingTransport;
  labels: ShoppingLabels;
  read: ShoppingRead;
  writes: ShoppingWrites;
};

/**
 * Delete with Undo: move_to_trash at the row's version, restore_from_trash at the trash version it answered with.
 * No question first, because Undo makes it reversible. The row leaves the list at once; a receipt row (`trashed`)
 * stands in the list until the time to undo is up or the list is left. Both writes go through the list's one write
 * path, so a retry keeps its idempotency key and a stale version is a conflict notice, not a second delete.
 * `onTrash` is absent when the host offers no delete.
 */
export function useItemTrash({ transport, labels: t, read, writes }: Params) {
  const { setDetail, written } = read;
  const { write } = writes;
  const [trashed, setTrashed] = useState<Record<string, TrashedItem>>({});
  const trashItem = transport.trashItem;
  const restoreItem = transport.restoreItem;

  /** The time to undo is up (or the item came back): the receipt row goes. */
  const release = useCallback((id: string) => {
    setTrashed((before) => {
      if (!(id in before)) return before;
      const rest = { ...before };
      delete rest[id];
      return rest;
    });
  }, []);

  /** Moves the item to the trash; `done` runs once it is there (the change form closes). */
  const onTrash =
    trashItem && restoreItem
      ? (item: ShoppingItem, done: () => void) =>
          void write(
            JSON.stringify(["trash", item.id, item.version]),
            (key) => trashItem(item.id, item.version, key),
            (result) => {
              written.delete(item.id);
              setDetail(
                (before) =>
                  before && {
                    ...before,
                    items: before.items.filter((entry) => entry.id !== item.id),
                  },
              );
              setTrashed((before) => ({
                ...before,
                [item.id]: { item, version: result.version },
              }));
              done();
            },
            item.id,
          )
      : undefined;

  /** Takes the item back out of the trash; the list is then read again and shows it. */
  function restore(receipt: TrashedItem) {
    if (!restoreItem) return;
    void write(
      JSON.stringify(["restore", receipt.item.id, receipt.version]),
      (key) => restoreItem(receipt.item.id, receipt.version, key),
      () => release(receipt.item.id),
      receipt.item.id,
    );
  }

  /** Forgets every receipt (another list or page was chosen). */
  const clear = useCallback(() => setTrashed({}), []);

  const receipts: Receipt[] = Object.values(trashed).map((receipt) => ({
    id: receipt.item.id,
    line: t.itemTrashed(receipt.item.name),
    undo: t.undoTrash,
    undoLabel: t.undoTrashNamed(receipt.item.name),
    failure: t.itemRestoreFailed(receipt.item.name),
    onUndo: () => restore(receipt),
  }));

  return { receipts, onTrash, release, clear };
}
