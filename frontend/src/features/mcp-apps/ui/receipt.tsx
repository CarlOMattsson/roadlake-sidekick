import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { UNDO_MS, useUndoHold } from "./undo-hold";
import "./receipt.css";

/**
 * The one receipt (kvittens) model: a change is confirmed in a small bar at the foot of the view, never as a line in
 * the content. It does not move what is on screen: in fullscreen it floats over the foot of the view (sticky, no
 * height of its own), inline it is added under the card's content, so nothing above it moves. It says what happened
 * ("Anteckningen sparades", "Återställd: Mjölk") and offers at most one undo ("Ångra", with the 15 s timeline) and
 * at most one way on ("Visa"). One receipt at a time: a new one replaces the old one, whose change stands.
 *
 * It goes away by itself: after `RECEIPT_MS` without Ångra, after `UNDO_MS` with it. The time stands still while the
 * pointer is over it or focus is in it. It is cleared when `resetKey` changes (the view navigates to another day,
 * entry or tab) and when the view unmounts, so an old receipt never comes back.
 *
 * A row's own state after a change (a done task's filled ring and "Klar", a bought item greyed) is not the receipt: the
 * row keeps its height and shows its new state; the receipt, with Ångra, is the bar.
 *
 * Usage: `const receipt = useReceipt(day)`; after a write, `receipt.show({ message, undo })`; render
 * `<ReceiptBar receipt={receipt} />` last in the view.
 */
export const RECEIPT_MS = 6000;

export type ReceiptInput = {
  /** What happened, as a short sentence without a full stop: "Anteckningen sparades". */
  message: string;
  /** Undo for the change; the bar then counts `UNDO_MS` and shows the timeline under the button. */
  undo?: { label: string; onUndo: () => unknown };
  /** One way on, e.g. "Visa" to the restored object. Pressing it also closes the receipt. */
  action?: { label: string; onClick: () => void };
};

export type Receipt = ReceiptInput & { id: number };

export type ReceiptState = {
  current: Receipt | null;
  show: (input: ReceiptInput) => void;
  clear: () => void;
  /** Clears the receipt only if it is still `id` (a newer one stays). */
  dismiss: (id: number) => void;
};

export function useReceipt(resetKey?: unknown): ReceiptState {
  const [current, setCurrent] = useState<Receipt | null>(null);
  const next = useRef(0);
  const show = useCallback((input: ReceiptInput) => {
    next.current += 1;
    setCurrent({ ...input, id: next.current });
  }, []);
  const clear = useCallback(() => setCurrent(null), []);
  const dismiss = useCallback(
    (id: number) => setCurrent((shown) => (shown?.id === id ? null : shown)),
    [],
  );
  // A new day, entry or tab: the receipt belonged to the old one.
  const firstKey = useRef(true);
  useEffect(() => {
    if (firstKey.current) {
      firstKey.current = false;
      return;
    }
    setCurrent(null);
  }, [resetKey]);
  return useMemo(
    () => ({ current, show, clear, dismiss }),
    [current, show, clear, dismiss],
  );
}

function CheckGlyph() {
  return (
    <svg
      className="sk-receipt__glyph"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  );
}

function ReceiptItem({
  receipt,
  onDismiss,
}: {
  receipt: Receipt;
  onDismiss: (id: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const { held, handlers } = useUndoHold(
    !busy,
    () => onDismiss(receipt.id),
    receipt.undo ? UNDO_MS : RECEIPT_MS,
  );
  const undo = receipt.undo;
  const action = receipt.action;
  return (
    <div
      className="sk-receipt"
      data-held={held || undefined}
      data-undo={undo ? "true" : undefined}
      {...handlers}
    >
      <CheckGlyph />
      <p className="sk-receipt__message">{receipt.message}</p>
      {action || undo ? (
        <div className="sk-receipt__actions">
          {action ? (
            <button
              type="button"
              className="sk-btn sk-btn--quiet sk-btn--compact sk-receipt__action"
              onClick={() => {
                action.onClick();
                onDismiss(receipt.id);
              }}
            >
              {action.label}
            </button>
          ) : null}
          {undo ? (
            <button
              type="button"
              className="sk-btn sk-btn--quiet sk-btn--compact sk-receipt__action sk-undo-time"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void Promise.resolve()
                  .then(() => undo.onUndo())
                  .finally(() => onDismiss(receipt.id));
              }}
            >
              {undo.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The bar of `useReceipt`. The slot is always in the page (a polite live region), so a screen reader hears each new
 * receipt; empty, it has no box.
 */
export function ReceiptBar({
  receipt,
  className,
}: {
  receipt: ReceiptState;
  className?: string;
}) {
  const { current, dismiss } = receipt;
  return (
    <div
      className={className ? `sk-receipt-slot ${className}` : "sk-receipt-slot"}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {current ? (
        <ReceiptItem key={current.id} receipt={current} onDismiss={dismiss} />
      ) : null}
    </div>
  );
}
