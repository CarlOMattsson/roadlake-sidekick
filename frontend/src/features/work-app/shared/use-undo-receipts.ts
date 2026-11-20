import { useEffect, useRef } from "react";
import type { ReceiptInput, ReceiptState } from "../../mcp-apps/ui/receipt";
import { shortTitle } from "../agenda/agenda-undo";

/**
 * What one row's change says in the receipt bar, and the Ångra that takes it back (absent where the host cannot write
 * the change back: the bar then only says what happened).
 */
export type UndoReceipt = {
  message: string;
  undo?: { label: string; onUndo: () => unknown };
};

/** A row's receipt text: what happened, then the row's title, cut at `UNDO_TITLE_MAX` ("Klar: Ring Karin"). */
export function rowReceipt(what: string, title: string): string {
  const name = shortTitle(title);
  return name ? `${what}: ${name}` : what;
}

/**
 * The bridge between a view's per-row Undo state and its receipt bar (designsystem §0.6, ui/receipt.tsx): the row keeps
 * its new state ("Klar", the filled ring) and its height while its change can be undone, and the change is confirmed,
 * with Ångra, in the bar at the view's foot. When a row gets a new Undo entry the bar shows it (`describe`); when the
 * bar's time is up, or a newer receipt replaces it, `onEnd` settles that row (its Undo runs out, a done row folds away).
 * When the row's entry goes first (Ångra used on the row, a read) the bar lets its receipt go without `onEnd`.
 *
 * Entries are compared by identity: a new object under a key is a new change. Several new entries in one render (a
 * queued write that lands together with another) show the last; the others end at once, as a replaced receipt does.
 * Ångra and the message are read from the latest `describe` when the bar's button is pressed, so it never writes
 * against a stale row.
 */
export function useUndoReceipts<U>({
  undos,
  receipt,
  describe,
  onEnd,
}: {
  undos: Readonly<Record<string, U>>;
  receipt: ReceiptState;
  /** The receipt of one row's entry; undefined shows none (and ends the row's entry at once). */
  describe: (key: string, undo: U) => UndoReceipt | undefined;
  onEnd: (key: string) => void;
}): void {
  const latest = useRef({ undos, describe, onEnd });
  useEffect(() => {
    latest.current = { undos, describe, onEnd };
  });
  const seen = useRef<Readonly<Record<string, U>>>({});
  // The row whose receipt the bar shows now, and the receipt's id.
  const shown = useRef<{ key: string; id: number } | null>(null);
  const { show, dismiss } = receipt;

  useEffect(() => {
    const before = seen.current;
    seen.current = undos;
    // The shown row's entry went (Ångra used, or forgotten by a read): its receipt goes too, with no onEnd.
    const now = shown.current;
    if (now && undos[now.key] === undefined) {
      shown.current = null;
      dismiss(now.id, true);
    }
    const added = Object.keys(undos).filter(
      (key) => undos[key] !== before[key],
    );
    if (!added.length) return;
    const last = added[added.length - 1]!;
    for (const key of added.slice(0, -1)) latest.current.onEnd(key);
    const entry = undos[last]!;
    const text = latest.current.describe(last, entry);
    if (!text) {
      latest.current.onEnd(last);
      return;
    }
    const input: ReceiptInput = {
      message: text.message,
      ...(text.undo
        ? {
            undo: {
              label: text.undo.label,
              onUndo: () => {
                const { undos: rows, describe: words } = latest.current;
                const held = rows[last];
                return held === undefined
                  ? undefined
                  : words(last, held)?.undo?.onUndo();
              },
            },
          }
        : {}),
      onEnd: () => {
        if (shown.current?.key === last) shown.current = null;
        // Only while the row still holds this change: a newer change of the same row has its own receipt.
        if (latest.current.undos[last] === entry) latest.current.onEnd(last);
      },
    };
    // The bar ends the receipt it replaces itself (its onEnd above), so the row it named settles there.
    shown.current = { key: last, id: show(input) };
    // `describe` and `onEnd` are read through `latest`: a new function each render is not a new change.
  }, [undos, show, dismiss]);
}
