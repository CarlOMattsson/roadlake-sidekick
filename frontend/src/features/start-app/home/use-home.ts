import { useCallback, useEffect, useRef, useState } from "react";

import type { StartHome } from "./model";
import type { HomeTransport } from "./transport";

type HomeRead =
  | { phase: "reading" }
  | { phase: "failed"; cause: unknown }
  | {
      phase: "ready";
      start: StartHome;
      /** A read again failed: the page stays, with the refresh line over it. */
      stale?: { cause: unknown };
    };

/**
 * Reads get_start: the result that opened the room when there is one, else a read of its own. `reload` reads again and
 * keeps the page on screen until the answer comes (a refresh in place, never a skeleton); a new `refreshKey` does the
 * same. An answer from a superseded read is dropped.
 */
export function useHome(
  api: HomeTransport,
  initial: StartHome | undefined,
  refreshKey = 0,
) {
  const [read, setRead] = useState<HomeRead>(
    initial ? { phase: "ready", start: initial } : { phase: "reading" },
  );
  const latest = useRef(0);
  const reload = useCallback(() => {
    const ticket = ++latest.current;
    api.read().then(
      (start) => {
        if (ticket === latest.current) setRead({ phase: "ready", start });
      },
      (cause: unknown) => {
        if (ticket !== latest.current) return;
        setRead((now) =>
          now.phase === "ready"
            ? { ...now, stale: { cause } }
            : { phase: "failed", cause },
        );
      },
    );
  }, [api]);
  const retry = useCallback(() => {
    setRead((now) => (now.phase === "failed" ? { phase: "reading" } : now));
    reload();
  }, [reload]);
  const seen = useRef(initial ? refreshKey : -1);
  useEffect(() => {
    if (seen.current === refreshKey) return;
    seen.current = refreshKey;
    reload();
  }, [refreshKey, reload]);
  return { read, reload, retry };
}
