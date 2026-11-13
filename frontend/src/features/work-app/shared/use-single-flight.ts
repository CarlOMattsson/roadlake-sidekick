import { useMemo, useRef } from "react";

export type SingleFlight = {
  /**
   * Claims the flight: true when the caller may start, false when one is already running for the same `generation`.
   * The claim is synchronous (a ref), so two clicks inside one render cannot both pass, which a check of rendered
   * state cannot promise. Without a generation, only one flight runs at a time.
   */
  enter: (generation?: number) => boolean;
  /** Releases the flight `enter` claimed for `generation`; a release for another generation changes nothing. */
  leave: (generation?: number) => void;
  /** True while any flight is claimed. For a caller that must skip its own side effects without claiming. */
  isRunning: () => boolean;
};

/**
 * A synchronous guard against a second start of the same work before React re-renders. The caller keeps whatever it
 * shows (a disabled button, "Saving…") in its own state; this holds only the question "is it running". A list that
 * pages passes its read generation: a read that a newer generation replaced stops counting, so the newer one may
 * start while the older answer is still on its way (the caller drops that answer).
 */
export function useSingleFlight(): SingleFlight {
  const running = useRef<number | undefined>(undefined);
  // One object for the life of the component, so callers may list it as a dependency.
  return useMemo(
    () => ({
      enter: (generation = 0) => {
        if (running.current === generation) return false;
        running.current = generation;
        return true;
      },
      leave: (generation = 0) => {
        if (running.current === generation) running.current = undefined;
      },
      isRunning: () => running.current !== undefined,
    }),
    [],
  );
}
