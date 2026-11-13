import { useCallback, useEffect, useRef, useState } from "react";
import { shiftDate } from "./dates";
import { EntryRow } from "./entry-row";
import type { JournalLabels } from "./labels";
import type { JournalEntry, JournalTransport } from "./transport";
import { EmptyState, ErrorNotice } from "../mcp-apps/ui/states";
import { tagLabelOf, type TagOption } from "../mcp-apps/ui/tag-vocabulary";

/** list_journal_entries takes at most 366 inclusive days: a window is a day and the 365 before it. */
const WINDOW_DAYS = 365;
/** Pages of 50 followed for one window, so a window holds at most 500 entries. */
const PAGE_LIMIT = 10;
/** Entries drawn at once; "Visa fler" draws this many more of those already read before it reads an older window. */
const ENTRIES_PER_PAGE = 50;
/** Empty windows in a row after which the list stops reading further back: two years without one such entry. */
const EMPTY_WINDOWS_TO_STOP = 2;

type Ready = {
  kind: "ready";
  entries: JournalEntry[];
  /** How many of `entries` are drawn; the rest follow ENTRIES_PER_PAGE at a time. */
  visible: number;
  capped: boolean;
  /** Windows of 366 days read back from today; "Visa fler" reads one more. */
  years: number;
  more: "idle" | "busy" | "failed" | "empty";
  /** Windows read in a row, newest last, that held no entry; at EMPTY_WINDOWS_TO_STOP the list ends. */
  emptyRun: number;
};
type Read = { kind: "loading" } | Ready | { kind: "error"; cause: unknown };

/**
 * The entries that carry every chosen tag, newest first: the last 12 months, and with "Visa fler" the 366 days before
 * the oldest window read, one window at a time. The server lists each window newest first, so its pages are followed in
 * order. A window that runs past the page limit shows its newest entries, says so and offers no older window. After two empty windows in a row the list says there is nothing older
 * and offers no "Visa fler", so the button cannot step back through empty years forever. A new `refreshKey` reads the last 12 months again in place, without the
 * loading line. The view's heading names the list ("Taggade anteckningar"), so the section has no heading of its own.
 */
export function TaggedEntries({
  tags,
  today,
  transport,
  labels: t,
  vocabulary,
  refreshKey,
  onOpen,
}: {
  tags: string[];
  today: string;
  transport: JournalTransport;
  labels: JournalLabels;
  vocabulary: readonly TagOption[];
  refreshKey?: number;
  onOpen: (id: string) => void;
}) {
  const [read, setRead] = useState<Read>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const list = transport.listTaggedEntries;
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  /** The window of 366 days that ends `back` windows before today, its entries newest first. */
  const readWindow = useCallback(
    async (back: number) => {
      if (!list) return { entries: [], capped: false };
      const to = shiftDate(today, -(WINDOW_DAYS + 1) * back);
      const from = shiftDate(to, -WINDOW_DAYS);
      const entries: JournalEntry[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < PAGE_LIMIT; page++) {
        const got = await list(tags, from, to, cursor);
        entries.push(...got.entries);
        cursor = got.next_cursor;
        if (!cursor) break;
      }
      return { entries, capped: cursor !== null };
    },
    [list, tags, today],
  );
  useEffect(() => {
    let current = true;
    readWindow(0).then(
      ({ entries, capped }) => {
        if (current)
          setRead({
            kind: "ready",
            entries,
            visible: ENTRIES_PER_PAGE,
            capped,
            years: 1,
            more: "idle",
            emptyRun: entries.length > 0 ? 0 : 1,
          });
      },
      (cause: unknown) => {
        if (current) setRead({ kind: "error", cause });
      },
    );
    return () => {
      current = false;
    };
  }, [readWindow, attempt, refreshKey]);
  /** "Visa fler": the entries already read first, then the 12 months before the oldest read, added under the list. */
  function showMore() {
    if (read.kind !== "ready" || read.more === "busy") return;
    if (read.visible < read.entries.length)
      setRead({ ...read, visible: read.visible + ENTRIES_PER_PAGE });
    else readOlder(read);
  }
  function readOlder(shown: Ready) {
    setRead({ ...shown, more: "busy" });
    readWindow(shown.years).then(
      ({ entries, capped }) => {
        if (!mounted.current) return;
        setRead({
          kind: "ready",
          entries: [...shown.entries, ...entries],
          visible: shown.entries.length + ENTRIES_PER_PAGE,
          capped,
          years: shown.years + 1,
          more: entries.length > 0 ? "idle" : "empty",
          emptyRun: entries.length > 0 ? 0 : shown.emptyRun + 1,
        });
      },
      () => {
        if (mounted.current) setRead({ ...shown, more: "failed" });
      },
    );
  }

  const names = tags.map((slug) => tagLabelOf(slug, vocabulary));
  const ended = read.kind === "ready" && read.emptyRun >= EMPTY_WINDOWS_TO_STOP;
  // Every entry read is drawn: only then do the notes on how far the read went apply.
  const allShown = read.kind === "ready" && read.visible >= read.entries.length;
  return (
    <section className="journal-tagged" aria-label={t.taggedEntries}>
      <p className="journal-muted">
        {t.taggedScope(names, read.kind === "ready" ? read.years : 1)}
      </p>
      {read.kind === "loading" && <p role="status">{t.loading}</p>}
      {read.kind === "error" && (
        <ErrorNotice
          locale={t.dateLocale}
          cause={read.cause}
          onRetry={() => {
            setRead({ kind: "loading" });
            setAttempt((n) => n + 1);
          }}
        />
      )}
      {read.kind === "ready" && read.entries.length === 0 && (
        <EmptyState title={t.taggedNone(tags.length, read.years)} />
      )}
      {read.kind === "ready" && read.entries.length > 0 && (
        <ul className="journal-timeline">
          {read.entries.slice(0, read.visible).map((entry) => (
            <EntryRow
              key={entry.id}
              entry={entry}
              labels={t}
              tagVocabulary={vocabulary}
              dated
              onOpen={() => onOpen(entry.id)}
            />
          ))}
        </ul>
      )}
      {read.kind === "ready" && read.capped && allShown && (
        <p className="journal-muted" role="status">
          {t.taggedCapped(read.entries.length)}
        </p>
      )}
      {/* The list ended after empty years: with entries the note says how far the read went; without any, the empty
          line above has already named the years. */}
      {read.kind === "ready" &&
        read.more === "empty" &&
        allShown &&
        (read.entries.length === 0 && ended ? null : (
          <p className="journal-muted" role="status">
            {ended
              ? t.taggedStopped(tags.length)
              : t.taggedNoOlder(tags.length)}
          </p>
        ))}
      {read.kind === "ready" && read.more === "busy" && (
        <p role="status">{t.loading}</p>
      )}
      {read.kind === "ready" && read.more === "failed" && (
        <ErrorNotice locale={t.dateLocale} onRetry={() => readOlder(read)} />
      )}
      {/* More of what was read, then the 12 months before the oldest read; none once a window was cut at the page limit
          or the list has ended. */}
      {read.kind === "ready" &&
        (!allShown || (!read.capped && !ended)) &&
        read.more !== "failed" && (
          <p className="journal-list-more">
            <button
              type="button"
              className="sk-btn--quiet"
              disabled={read.more === "busy"}
              onClick={showMore}
            >
              {t.taggedMore}
            </button>
          </p>
        )}
    </section>
  );
}
