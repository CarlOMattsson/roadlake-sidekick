import { useLayoutEffect, useRef, useState } from "react";

/**
 * What a control view shows, and the card told about every change to it. The card keeps the newest data so a switch
 * away and back shows it, not the first read. The card is told in the same step that changes the data, not from an
 * effect: an effect runs after the next frame, and leaving the tab before then would drop the change.
 *
 * A new `initial` is a fresh read from the card (a refresh): it replaces the data, is not reported back, and
 * leaves what the view holds on screen (busy, notices, focus) alone. `onFresh` runs then, for state of the view's
 * own that the new data invalidates.
 *
 * `change` computes the next data from the newest one, also in code that runs after an await.
 */
export function useReportedData<S>(
  initial: S,
  onData?: (data: NonNullable<S>) => void,
  onFresh?: () => void,
) {
  const [value, setValue] = useState(initial);
  const latest = useRef(initial);
  const [seenInitial, setSeenInitial] = useState(initial);
  if (initial !== seenInitial) {
    setSeenInitial(initial);
    setValue(initial);
    onFresh?.();
  }
  // Keeps `latest` on what is shown whenever a render, not `change`, set it (a fresh read from the card).
  useLayoutEffect(() => {
    latest.current = value;
  }, [value]);
  function change(update: (current: S) => NonNullable<S>) {
    const next = update(latest.current);
    latest.current = next;
    setValue(next);
    onData?.(next);
  }
  return [value, change] as const;
}
