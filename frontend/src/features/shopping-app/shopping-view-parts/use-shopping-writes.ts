import { useRef, useState } from "react";
import { isConflict, writeKey } from "../transport";
import type { ShoppingRead } from "./use-shopping-read";

/**
 * The list-level write: one at a time, with a key kept across uncertain delivery, a conflict notice (the row
 * changed elsewhere) and the failed write that "Try again" repeats.
 */
export function useShoppingWrites(read: ShoppingRead) {
  const { busy, setBusy, setError, reload } = read;
  // The last write was refused because the row changed elsewhere. The list is read again; no retry of the old version.
  // The notice stands in the row the user tapped (at the top it was out of sight in a scrolled list), else at the top.
  const [conflict, setConflict] = useState<{ rowId: string | null } | null>(
    null,
  );
  // The failed write that "Try again" repeats. It keeps the key of its attempt.
  const [failedWrite, setFailedWrite] = useState<(() => void) | null>(null);
  // Retain a write identity across uncertain delivery. A changed intent gets a new key.
  const intent = useRef<{ fingerprint: string; key: string } | null>(null);
  async function write<R>(
    fingerprint: string,
    action: (key: string) => Promise<R>,
    success?: (result: R) => void,
    rowId: string | null = null,
  ): Promise<boolean> {
    if (busy) return false;
    setConflict(null);
    if (intent.current?.fingerprint !== fingerprint)
      intent.current = { fingerprint, key: writeKey() };
    setBusy(true);
    setError(null);
    try {
      const result = await action(intent.current.key);
      intent.current = null;
      setFailedWrite(null);
      success?.(result);
      await reload();
      return true;
    } catch (caught) {
      if (isConflict(caught)) {
        // The stored version moved on, so repeating this write with the same version can never succeed.
        // The intent is dropped and the list is read again; the next tap is a new write with the new version.
        intent.current = null;
        setFailedWrite(null);
        setConflict({ rowId });
        setBusy(false);
        await reload();
        return false;
      }
      // "Try again" repeats this write; its intent is kept, so the retry reuses the same key.
      setFailedWrite(
        () => () => void write(fingerprint, action, success, rowId),
      );
      setError({ rowId });
      setBusy(false);
      return false;
    }
  }
  return { conflict, setConflict, failedWrite, setFailedWrite, write };
}

export type ShoppingWrites = ReturnType<typeof useShoppingWrites>;
