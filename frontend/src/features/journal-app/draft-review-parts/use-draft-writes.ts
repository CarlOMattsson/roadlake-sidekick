import { useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../mcp-apps/idempotency";
import { writeFailure } from "../transport";

export type WriteAction = "save" | "reload" | "reject" | "finalize";

export type WriteState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "saved" }
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "invalid" }
  | { kind: "failed"; action: WriteAction };

function failureState(error: unknown, action: WriteAction): WriteState {
  const kind = writeFailure(error);
  // A record that is gone (not_found) has no state of its own here; it reads as a failed action.
  if (kind === "failed" || kind === "not_found")
    return { kind: "failed", action };
  return { kind };
}

/**
 * The write status of the draft frame and the guards around one write at a time: a synchronous in-flight flag
 * (a double click gets in before React re-renders), the idempotency key of the current attempt, and a mounted
 * flag so a late answer never touches an unmounted frame.
 */
export function useDraftWrites() {
  const [write, setWrite] = useState<WriteState>({ kind: "idle" });
  const mounted = useRef(true);
  const writing = useRef(false);
  const pendingWrite = useRef<PendingKey | undefined>(undefined);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** The key of this attempt: the same for the same signature, a new one when the signature changes. */
  function keyedBy(signature: string): PendingKey {
    const pendingKey = keyFor(pendingWrite.current, signature);
    pendingWrite.current = pendingKey;
    return pendingKey;
  }
  function isWriting(): boolean {
    return writing.current;
  }
  /** Forgets the key, so the next attempt is a new write. */
  function discardKey() {
    pendingWrite.current = undefined;
  }
  /**
   * Runs one write: busy while it is in flight, `onDone` on success (key already forgotten), the failure
   * state on error. Nothing is applied once the frame is unmounted.
   */
  function perform<T>(
    action: WriteAction,
    start: () => Promise<T>,
    onDone: (result: T) => void,
  ) {
    writing.current = true;
    setWrite({ kind: "busy" });
    start()
      .then((result) => {
        if (!mounted.current) return;
        pendingWrite.current = undefined;
        onDone(result);
      })
      .catch((error: unknown) => {
        if (mounted.current) setWrite(failureState(error, action));
      })
      .finally(() => {
        writing.current = false;
      });
  }

  return {
    write,
    setWrite,
    busy: write.kind === "busy",
    keyedBy,
    isWriting,
    discardKey,
    perform,
  };
}
