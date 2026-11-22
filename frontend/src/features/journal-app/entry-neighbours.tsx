import { useCallback, useEffect, useMemo, useState } from "react";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ChevronLeftIcon, ChevronRightIcon } from "../mcp-apps/ui/icons";
import { formatDayHeading, shiftDate } from "./dates";
import type { JournalLabels } from "./labels";
import type { JournalEntry, JournalTransport } from "./transport";
import "./entry.css";
import "./entry-read.css";

/** How far from the entry's day the nearest day with entries is looked for. */
const REACH_DAYS = 90;

/**
 * The entry before or after the open one. In the same day it is known by id and title; on the nearest other day with
 * entries only the day is known (`id` absent), and the entry is read when the owner steps there.
 */
export type Neighbour = { date: string; id?: string; title?: string };
export type Neighbours = { previous?: Neighbour; next?: Neighbour };
export type Side = "previous" | "next";

/**
 * The neighbours of `entry`, as the day lists them (oldest first, the way the day view shows them). At the first or
 * last entry of the day the nearest day with entries is looked up in one read of the dates each way, when the
 * transport can list them; without that the stepping stays inside the day. A read that fails leaves no neighbour:
 * the buttons are a convenience and never an error.
 */
export function useEntryNeighbours(
  transport: JournalTransport,
  entry: JournalEntry | undefined,
): {
  neighbours: Neighbours;
  /** The id of the entry at `side`, reading its day first when only the day is known; undefined when it fails. */
  resolve: (side: Side) => Promise<string | undefined>;
} {
  const id = entry?.id;
  const date = entry?.journal_date;
  const [found, setFound] = useState<{ id: string; value: Neighbours }>();
  useEffect(() => {
    if (!id || !date) return undefined;
    let current = true;
    const reach = transport.listEntryDates;
    async function nearest(
      from: string,
      to: string,
      pick: (dates: string[]) => string | undefined,
    ): Promise<Neighbour | undefined> {
      if (!reach) return undefined;
      const dates = await reach(from, to).catch(() => []);
      const day = pick(dates);
      return day ? { date: day } : undefined;
    }
    (async () => {
      const day = await transport.getDay(date);
      const at = day.entries.findIndex((item) => item.id === id);
      if (at < 0) return {};
      const before = day.entries[at - 1];
      const after = day.entries[at + 1];
      return {
        previous: before
          ? { date, id: before.id, title: before.title }
          : await nearest(
              shiftDate(date, -REACH_DAYS),
              shiftDate(date, -1),
              (dates) =>
                dates
                  .filter((value) => value < date)
                  .sort()
                  .at(-1),
            ),
        next: after
          ? { date, id: after.id, title: after.title }
          : await nearest(
              shiftDate(date, 1),
              shiftDate(date, REACH_DAYS),
              (dates) =>
                dates
                  .filter((value) => value > date)
                  .sort()
                  .at(0),
            ),
      } satisfies Neighbours;
    })().then(
      (value) => {
        if (current) setFound({ id, value });
      },
      () => {
        if (current) setFound({ id, value: {} });
      },
    );
    return () => {
      current = false;
    };
    // A saved change (version) can move the entry's place in its day.
  }, [transport, id, date, entry?.version]);

  const neighbours = useMemo(
    () => (found && found.id === id ? found.value : {}),
    [found, id],
  );
  const resolve = useCallback(
    async (side: Side): Promise<string | undefined> => {
      const target = neighbours[side];
      if (!target) return undefined;
      if (target.id) return target.id;
      try {
        const day = await transport.getDay(target.date);
        return (side === "previous" ? day.entries.at(-1) : day.entries.at(0))
          ?.id;
      } catch {
        return undefined;
      }
    },
    [neighbours, transport],
  );
  return { neighbours, resolve };
}

/**
 * "‹ Previous entry" and "Next entry ›" at the end of the entry view, each 44 high and with the neighbour's title (or,
 * on another day, its day) under the name. Draws nothing when the entry has no neighbour.
 */
export function EntryNeighbours({
  labels: t,
  neighbours,
  disabled,
  onStep,
}: {
  labels: JournalLabels;
  neighbours: Neighbours;
  disabled: boolean;
  onStep: (side: Side) => void;
}) {
  const { previous, next } = neighbours;
  if (!previous && !next) return null;
  function line(neighbour: Neighbour): string {
    return (
      neighbour.title ??
      formatDayHeading(neighbour.date, t.dateLocale, ownerToday())
    );
  }
  return (
    <nav className="journal-neighbours" aria-label={t.neighbours}>
      {previous ? (
        <button
          type="button"
          className="journal-neighbour journal-neighbour--previous"
          disabled={disabled}
          aria-keyshortcuts="k"
          onClick={() => onStep("previous")}
        >
          <ChevronLeftIcon />
          <span className="journal-neighbour__text">
            <span className="journal-neighbour__kind">{t.previousEntry}</span>
            <span className="journal-neighbour__name">{line(previous)}</span>
          </span>
        </button>
      ) : (
        <span />
      )}
      {next ? (
        <button
          type="button"
          className="journal-neighbour journal-neighbour--next"
          disabled={disabled}
          aria-keyshortcuts="j"
          onClick={() => onStep("next")}
        >
          <span className="journal-neighbour__text">
            <span className="journal-neighbour__kind">{t.nextEntry}</span>
            <span className="journal-neighbour__name">{line(next)}</span>
          </span>
          <ChevronRightIcon />
        </button>
      ) : (
        <span />
      )}
    </nav>
  );
}
