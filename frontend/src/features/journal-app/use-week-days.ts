import { useCallback, useEffect, useRef, useState } from "react";
import { isForbidden } from "./transport";
import type { JournalDay, JournalTransport } from "./transport";

export type WeekRead =
  | { phase: "loading" }
  | { phase: "ready"; days: JournalDay[] }
  | { phase: "forbidden" }
  | { phase: "error"; cause: unknown };

type Answer = { key: string; days?: JournalDay[]; cause?: unknown };

/**
 * The days of one week as get_journal_day returns them (entries, summary and what was done), read together, one
 * call per date. A new set of dates shows `loading` until all of them have answered; a new `refreshKey` reads the same
 * dates again in place, so the week stays on screen. One failed day fails the week, and `retry` reads it again. A read
 * that lands after the dates changed or the view went away is dropped.
 */
export function useWeekDays(
  transport: JournalTransport,
  dates: readonly string[],
  refreshKey: number | undefined,
): { read: WeekRead; retry: () => void } {
  const key = dates.join(",");
  const latest = useRef({ transport, dates });
  useEffect(() => {
    latest.current = { transport, dates };
  });
  const [answer, setAnswer] = useState<Answer>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const { transport: source, dates: wanted } = latest.current;
    if (wanted.length === 0) {
      setAnswer({ key, days: [] });
      return;
    }
    let current = true;
    Promise.all(wanted.map((date) => source.getDay(date))).then(
      (days) => {
        if (current) setAnswer({ key, days });
      },
      (cause: unknown) => {
        // A failed refresh leaves the week that is shown.
        if (current)
          setAnswer((shown) =>
            shown?.key === key && shown.days ? shown : { key, cause },
          );
      },
    );
    return () => {
      current = false;
    };
  }, [key, refreshKey, attempt]);
  const retry = useCallback(() => {
    setAnswer(undefined);
    setAttempt((n) => n + 1);
  }, []);
  if (answer?.key !== key) return { read: { phase: "loading" }, retry };
  if (answer.days)
    return { read: { phase: "ready", days: answer.days }, retry };
  return {
    read: isForbidden(answer.cause)
      ? { phase: "forbidden" }
      : { phase: "error", cause: answer.cause },
    retry,
  };
}
