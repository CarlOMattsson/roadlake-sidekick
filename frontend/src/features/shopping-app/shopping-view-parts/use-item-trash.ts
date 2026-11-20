import type { ShoppingItem, ShoppingTransport } from "../transport";
import type { ShoppingLabels } from "../labels";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import type { ShoppingRead } from "./use-shopping-read";
import type { ShoppingWrites } from "./use-shopping-writes";

type Params = {
  transport: ShoppingTransport;
  labels: ShoppingLabels;
  read: ShoppingRead;
  writes: ShoppingWrites;
  /** The view's receipt bar: a delete is confirmed there, with Ångra. */
  receipt: ReceiptState;
  /** A failed Ångra: the view names it in its message box, since the row is gone from the list. */
  onUndoFailed: (id: string, message: string) => void;
};

/**
 * Delete with Undo: move_to_trash at the row's version, restore_from_trash at the trash version it answered with.
 * No question first, because Undo makes it reversible. The row leaves the list at once and the receipt bar says so,
 * with Ångra, which holds the trash version. Both writes go through the list's one write path, so a retry keeps its
 * idempotency key and a stale version is a conflict notice, not a second delete. `onTrash` is absent when the host
 * offers no delete. `discard` is the same delete without a receipt of its own: the Ångra of an add.
 */
export function useItemTrash({
  transport,
  labels: t,
  read,
  writes,
  receipt,
  onUndoFailed,
}: Params) {
  const { setDetail, written } = read;
  const { write } = writes;
  const trashItem = transport.trashItem;
  const restoreItem = transport.restoreItem;

  /** The write of a delete; `done` runs with the trash version once the item is there. */
  function trashWrite(
    item: ShoppingItem,
    done?: (version: number) => void,
  ): Promise<boolean> {
    if (!trashItem) return Promise.resolve(false);
    return write(
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
        done?.(result.version);
      },
      item.id,
    );
  }

  /** Takes the item back out of the trash; the list is then read again and shows it. */
  async function restore(item: ShoppingItem, version: number) {
    if (!restoreItem) return;
    const ok = await write(
      JSON.stringify(["restore", item.id, version]),
      (key) => restoreItem(item.id, version, key),
      undefined,
      item.id,
    );
    if (!ok) onUndoFailed(item.id, t.itemRestoreFailed(item.name));
  }

  /** Moves the item to the trash; `done` runs once it is there (the change form closes), and the bar says so. */
  const onTrash =
    trashItem && restoreItem
      ? (item: ShoppingItem, done: () => void) =>
          void trashWrite(item, (version) => {
            receipt.show({
              message: t.itemTrashed(item.name),
              undo: {
                label: t.undoTrash,
                onUndo: () => restore(item, version),
              },
            });
            done();
          })
      : undefined;

  /** The Ångra of an add: the new item goes to the trash, with no receipt of its own (the add's receipt was it). */
  const discard =
    trashItem && restoreItem
      ? (item: ShoppingItem) => trashWrite(item)
      : undefined;

  return { onTrash, discard };
}
