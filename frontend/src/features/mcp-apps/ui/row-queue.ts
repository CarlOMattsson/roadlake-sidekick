import { useEffect, useMemo, useRef, useState } from "react";

/**
 * A write queue per row. A tap on a row whose write is still running is not dropped: it
 * waits behind that write and runs when it is done, and `queued(key)` says so, so the row can show that the tap
 * was received. Rows are independent: writes to different rows run at the same time. A task handles its own
 * errors; one that throws anyway does not stop the rows behind it.
 */
export type RowQueue = {
  /** Runs `task` after the earlier tasks of the same row. */
  enqueue: (key: string, task: () => Promise<void>) => Promise<void>;
  /** The tasks of the row that are running or waiting. */
  pending: (key: string) => number;
  /** Whether a tap of the row waits behind a running write: the row shows the waiting mark. */
  queued: (key: string) => boolean;
};

export function useRowQueue(): RowQueue {
  const counts = useRef(new Map<string, number>());
  const tails = useRef(new Map<string, Promise<void>>());
  const alive = useRef(true);
  const [, setTick] = useState(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  return useMemo<RowQueue>(() => {
    const bump = () => {
      if (alive.current) setTick((n) => n + 1);
    };
    return {
      enqueue(key, task) {
        counts.current.set(key, (counts.current.get(key) ?? 0) + 1);
        bump();
        const next = (tails.current.get(key) ?? Promise.resolve())
          .then(task)
          .catch(() => undefined)
          .finally(() => {
            const left = (counts.current.get(key) ?? 1) - 1;
            if (left > 0) counts.current.set(key, left);
            else {
              counts.current.delete(key);
              tails.current.delete(key);
            }
            bump();
          });
        tails.current.set(key, next);
        return next;
      },
      pending: (key) => counts.current.get(key) ?? 0,
      queued: (key) => (counts.current.get(key) ?? 0) > 1,
    };
  }, []);
}
