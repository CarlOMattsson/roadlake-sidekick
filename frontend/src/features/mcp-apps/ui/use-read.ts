import { useCallback, useEffect, useState } from "react";

/** A read: reading, read, or failed (with why). */
export type Read<T> =
  | { phase: "reading" }
  | { phase: "ready"; value: T }
  | { phase: "failed"; cause: unknown };

/**
 * Reads once per `read` and per `refreshKey`, and again on the returned retry (which goes back to "reading"). `read`
 * must be stable (useCallback); without one nothing is read and the state stays as it was. A new `read` or
 * `refreshKey` keeps the last result on screen until the new answer arrives, and an answer from a superseded read
 * or an unmounted caller is dropped.
 *
 * `initial` is a result the caller already holds: it is the first state, and the first read is skipped. Only a retry
 * reads it again. Whether one was given is fixed at mount.
 *
 * The third element replaces the result with a value the caller got another way (the reply to a write).
 */
export function useRead<T>(
  read: (() => Promise<T>) | undefined,
  refreshKey = 0,
  initial?: T,
): [Read<T>, () => void, (value: T) => void] {
  const [carried] = useState(initial !== undefined);
  const [state, setState] = useState<Read<T>>(
    initial === undefined
      ? { phase: "reading" }
      : { phase: "ready", value: initial },
  );
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!read || (carried && attempt === 0)) return undefined;
    let live = true;
    // A read that throws at once is a failed read too.
    new Promise<T>((resolve) => resolve(read())).then(
      (value) => {
        if (live) setState({ phase: "ready", value });
      },
      (cause: unknown) => {
        if (live) setState({ phase: "failed", cause });
      },
    );
    return () => {
      live = false;
    };
  }, [read, refreshKey, attempt, carried]);
  const retry = useCallback(() => {
    setState({ phase: "reading" });
    setAttempt((value) => value + 1);
  }, []);
  const replace = useCallback(
    (value: T) => setState({ phase: "ready", value }),
    [],
  );
  return [state, retry, replace];
}
