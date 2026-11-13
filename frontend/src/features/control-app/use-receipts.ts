import { useEffect, useRef, useState } from "react";

/** How long a row's receipt stays ("Restored", "Bought again"), in milliseconds. */
export const RESTORED_MS = 5000;

/**
 * Receipts for rows whose write is saved: the row stays where it is and its meta line says what happened for
 * RESTORED_MS, then the receipt goes. A receipt is keyed by the row it belongs to; showing one for a key
 * that already has one starts its time again. Timers end with the view.
 */
export function useReceipts<V>() {
  const [receipts, setReceipts] = useState<ReadonlyMap<string, V>>(new Map());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const held = timers.current;
    return () => {
      held.forEach((timer) => clearTimeout(timer));
      held.clear();
    };
  }, []);

  function show(key: string, value: V) {
    clearTimeout(timers.current.get(key));
    setReceipts((current) => new Map(current).set(key, value));
    timers.current.set(
      key,
      setTimeout(() => {
        timers.current.delete(key);
        setReceipts((current) => {
          const next = new Map(current);
          next.delete(key);
          return next;
        });
      }, RESTORED_MS),
    );
  }

  return [receipts, show] as const;
}
