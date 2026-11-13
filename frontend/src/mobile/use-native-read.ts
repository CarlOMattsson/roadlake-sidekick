import { useEffect, useState } from "react";

/** A native read: reading, read, or failed (with a retry). `read` must be stable (useCallback). */
export type Read<T> =
  | { phase: "reading" }
  | { phase: "ready"; value: T }
  | { phase: "failed" };

export function useNativeRead<T>(
  read: () => Promise<T>,
  refreshKey: number,
): [Read<T>, () => void] {
  const [state, setState] = useState<Read<T>>({ phase: "reading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    read().then(
      (value) => {
        if (live) setState({ phase: "ready", value });
      },
      () => {
        if (live) setState({ phase: "failed" });
      },
    );
    return () => {
      live = false;
    };
  }, [read, refreshKey, attempt]);
  return [
    state,
    () => {
      setState({ phase: "reading" });
      setAttempt((value) => value + 1);
    },
  ];
}
