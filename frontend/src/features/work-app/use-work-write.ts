import { useCallback, useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../mcp-apps/idempotency";
import { writeFailure, type WriteFailure } from "./transport";

export type WorkWrite = {
  /** True while a write is in flight. Controls that start a write are disabled meanwhile. */
  busy: boolean;
  /** How the last write was refused; cleared when the next write starts or after clear(). */
  failure: WriteFailure | undefined;
  /**
   * Runs one durable write. `signature` names the action together with the versions it rests on:
   * running the same signature again after a lost or failed answer reuses one idempotency key, so
   * the server replays the result instead of writing twice. Any other signature gets a fresh key.
   * Resolves the value the write returned, or undefined when it failed (see `failure`) or when
   * another write was already running (a second click in the same tick is ignored).
   */
  run: <T>(
    signature: string,
    send: (idempotencyKey: string) => Promise<T>,
  ) => Promise<T | undefined>;
  /** Forgets the last failure, e.g. after the view has read the record again. */
  clear: () => void;
};

/**
 * The write guard the Work App's list controls share: one write at a time, one idempotency key per
 * user action, and the refusal sorted into conflict, forbidden, invalid, not_found or retryable. It holds no
 * view state, so each control decides what a conflict means for its own list.
 */
export function useWorkWrite(): WorkWrite {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<WriteFailure>();
  // Synchronous guard: a second click in the same tick must not start a second write.
  const writing = useRef(false);
  const pending = useRef<PendingKey | undefined>(undefined);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    async <T>(
      signature: string,
      send: (idempotencyKey: string) => Promise<T>,
    ): Promise<T | undefined> => {
      if (writing.current) return undefined;
      const key = keyFor(pending.current, signature);
      pending.current = key;
      writing.current = true;
      setBusy(true);
      setFailure(undefined);
      try {
        const value = await send(key.key);
        pending.current = undefined;
        return value;
      } catch (error: unknown) {
        const kind = writeFailure(error);
        // Only a retryable failure keeps its key; a refusal cannot be helped by sending it again.
        if (kind !== "failed") pending.current = undefined;
        if (mounted.current) setFailure(kind);
        return undefined;
      } finally {
        writing.current = false;
        if (mounted.current) setBusy(false);
      }
    },
    [],
  );
  const clear = useCallback(() => setFailure(undefined), []);
  return { busy, failure, run, clear };
}
