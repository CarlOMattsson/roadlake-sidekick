import { act, within } from "@testing-library/react";

const UNDO_NAME = /^(Undo|Ångra)$/;

/** The view's one receipt bar: the always-present live region the shared `ReceiptBar` renders last in the view. */
export function receiptSlot(): HTMLElement {
  const slot = document.querySelector<HTMLElement>(".sk-receipt-slot");
  if (!slot) throw new Error("the receipt bar is not in the page");
  return slot;
}

/** The receipt that shows now, or null when the bar is empty. */
export function receiptNow(): HTMLElement | null {
  return receiptSlot().querySelector<HTMLElement>(".sk-receipt");
}

/** The text of the receipt that shows now ("" when the bar is empty). */
export function receiptText(): string {
  return receiptNow()?.querySelector(".sk-receipt__message")?.textContent ?? "";
}

/** The Ångra/Undo button of the receipt that shows now (throws when there is none). */
export function receiptUndo(name: string | RegExp = UNDO_NAME) {
  return within(receiptSlot()).getByRole("button", { name });
}

/** The Ångra/Undo button of a receipt, once it shows. */
export function findReceiptUndo(name: string | RegExp = UNDO_NAME) {
  return within(receiptSlot()).findByRole("button", { name });
}

/**
 * Lets the shown receipt's countdown start before a test moves the fake clock. The bar starts its timer in a passive
 * effect, and under load (and `shouldAdvanceTime`) that effect can still be pending when the receipt's text and button
 * are already in the page: a clock moved then is moved before the countdown exists, and the receipt would run its full
 * time from the move. Await this after the receipt shows and before any `vi.advanceTimersByTime`.
 */
export async function receiptRunning(): Promise<void> {
  await act(async () => {});
}
