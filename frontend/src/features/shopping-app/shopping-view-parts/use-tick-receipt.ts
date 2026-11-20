import { useEffect, useRef } from "react";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import type { ShoppingLabels } from "../labels";
import type { ShoppingItem } from "../transport";
import type { usePurchases } from "./use-purchases";

type Params = {
  labels: ShoppingLabels;
  receipt: ReceiptState;
  purchases: ReturnType<typeof usePurchases>;
  /** The items as drawn now (asked purchases included). */
  items: ShoppingItem[];
  error: { rowId: string | null } | null;
  conflict: { rowId: string | null } | null;
};

/**
 * A tick of the ring, confirmed in the view's receipt bar (designsystem §3 Ångra): the row shows its new state in its
 * place, and the bar says what happened with Ångra. The held rows stay where they are while the bar shows (a run of
 * ticks replaces one receipt with the next) and all go where they belong together once it is empty, so nothing moves
 * under the thumb while ticking. A refused tick takes its receipt back. Answers the row's `onToggle`.
 */
export function useTickReceipt({
  labels: t,
  receipt,
  purchases,
  items,
  error,
  conflict,
}: Params) {
  const { held, waiting, togglePurchase, releaseAll } = purchases;
  const shown = receipt.current;
  useEffect(() => {
    if (!shown) releaseAll();
  }, [shown, releaseAll]);
  // The bar's Ångra runs long after the tap that showed it: it ticks the row as it is drawn then, with the newest
  // purchase handler (which knows the row is held).
  const toggleNow = useRef(togglePurchase);
  const itemsNow = useRef(items);
  useEffect(() => {
    toggleNow.current = togglePurchase;
    itemsNow.current = items;
  });
  // The receipt of the last tick, so a refusal of that write takes its receipt back.
  const tickReceipt = useRef<{ itemId: string; receiptId: number } | null>(
    null,
  );
  const { dismiss } = receipt;
  useEffect(() => {
    const tick = tickReceipt.current;
    const failed = error?.rowId ?? conflict?.rowId;
    if (!tick || failed !== tick.itemId) return;
    tickReceipt.current = null;
    dismiss(tick.receiptId);
  }, [error, conflict, dismiss]);

  return function toggle(item: ShoppingItem) {
    if (item.id in waiting) return;
    // A tap on a held row takes its change back: that is the undo, so its receipt offers none.
    const undoing = item.id in held;
    void togglePurchase(item);
    const message = `${item.purchased ? t.notBought : t.bought}: ${item.name}`;
    const receiptId = receipt.show(
      undoing
        ? { message }
        : {
            message,
            undo: {
              label: t.undoPurchase,
              // The bar holds (Ångra busy) until the row's write has run: the held rows are not let go under it.
              onUndo: () => {
                const now = itemsNow.current.find(
                  (entry) => entry.id === item.id,
                );
                return now ? toggleNow.current(now) : undefined;
              },
            },
          },
    );
    tickReceipt.current = { itemId: item.id, receiptId };
  };
}
