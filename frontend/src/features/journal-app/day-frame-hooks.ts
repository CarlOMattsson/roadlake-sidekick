import { useEffect, useRef, useState } from "react";
import type { JournalDay, JournalFrame, JournalTransport } from "./transport";

/** True while the owning component is mounted, so a read that lands later can be dropped. */
export function useMountedRef() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}

type DayFrameValue = Extract<JournalFrame, { kind: "day" }>;

/**
 * A changed refreshKey reads the shown day again, in place: no day change, no loading state, and the
 * expanded day and the scroll position stay. A read that lands after the owner moved on is dropped.
 */
export function useDayRefresh(
  refreshKey: number | undefined,
  mounted: { current: boolean },
  current: {
    frame: DayFrameValue;
    loading: boolean;
    transport: JournalTransport;
    onChange: (next: JournalFrame) => void;
  },
) {
  // The latest values, so the read below uses the day as it is when the request arrives.
  const latest = useRef(current);
  useEffect(() => {
    latest.current = current;
  });
  const refreshAtMount = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === refreshAtMount.current) return;
    refreshAtMount.current = refreshKey;
    const shown = latest.current;
    // A day the owner is moving to is read by its own step; that read replaces the frame.
    if (shown.loading) return;
    shown.transport.getDay(shown.frame.page.journal_date).then(
      (next: JournalDay) => {
        if (!mounted.current || latest.current.frame !== shown.frame) return;
        shown.onChange({ ...shown.frame, page: next });
      },
      () => undefined,
    );
  }, [refreshKey, mounted]);
}

/**
 * The days with entries behind the dots in the strip: one list_journal_entries read (dates only) per shown seven
 * days, again on a refresh. Kept per range, so stepping back to seven days already read shows their dots at once
 * while they are read again.
 */
export function useEntryDates(
  transport: JournalTransport,
  rangeFrom: string | undefined,
  rangeTo: string | undefined,
  refreshKey: number | undefined,
): string[] {
  const latestTransport = useRef(transport);
  useEffect(() => {
    latestTransport.current = transport;
  });
  const [entryDates, setEntryDates] = useState<Record<string, string[]>>({});
  useEffect(() => {
    const list = latestTransport.current.listEntryDates;
    if (!list || !rangeFrom || !rangeTo) return;
    const range = `${rangeFrom}/${rangeTo}`;
    let current = true;
    list(rangeFrom, rangeTo).then(
      (dates) => {
        if (current) setEntryDates((known) => ({ ...known, [range]: dates }));
      },
      // A failed read leaves the dots as they were: the day the view has read still gets its own.
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [rangeFrom, rangeTo, refreshKey]);
  return entryDates[`${rangeFrom}/${rangeTo}`] ?? [];
}
