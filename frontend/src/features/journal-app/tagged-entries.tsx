import { useCallback, useEffect, useRef, useState } from "react";
import { shiftDate } from "./dates";
import { EntryRow } from "./entry-row";
import type { JournalLabels } from "./labels";
import type { JournalEntry, JournalTransport } from "./transport";
import { EmptyState, ErrorNotice } from "../mcp-apps/ui/states";
import { tagLabelsFor } from "../mcp-apps/ui/tag-labels";
import { tagLabelOf, type TagOption } from "../mcp-apps/ui/tag-vocabulary";

/** list_journal_entries takes at most 366 inclusive days: a window is a day and the 365 before it. */
const WINDOW_DAYS = 365;
/** Pages of 50 followed for one window, so a window holds at most 500 entries. */
const PAGE_LIMIT = 10;

type Read =
  | { kind: "loading" }
  | {
      kind: "ready";
      entries: JournalEntry[];
      capped: boolean;
      /** Windows of 366 days read back from today; "Visa fler" reads one more. */
      years: number;
      more: "idle" | "busy" | "failed" | "empty";
    }
  | { kind: "error"; cause: unknown };

/**
 * The entries that carry every chosen tag, newest first: the last 12 months, and with "Visa fler" the 366 days before
 * the oldest window read, one window at a time. The server lists a window oldest first and cannot turn the order round,
 * so its pages are followed to the end and reversed here. A window that runs past the page limit shows its oldest
 * entries, says so and offers no older window. A new `refreshKey` reads the last 12 months again in place, without the
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
  /** The window of 366 days that ends `back` windows before today, newest first. */
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
      return { entries: entries.reverse(), capped: cursor !== null };
    },
    [list, tags, today],
  );
  useEffect(() => {
    let current = true;
    readWindow(0).then(
      ({ entries, capped }) => {
        if (current)
          setRead({ kind: "ready", entries, capped, years: 1, more: "idle" });
      },
      (cause: unknown) => {
        if (current) setRead({ kind: "error", cause });
      },
    );
    return () => {
      current = false;
    };
  }, [readWindow, attempt, refreshKey]);
  /** "Visa fler": the 12 months before the oldest read, added under the list. */
  function readOlder() {
    if (read.kind !== "ready" || read.more === "busy") return;
    const shown = read;
    setRead({ ...shown, more: "busy" });
    readWindow(shown.years).then(
      ({ entries, capped }) => {
        if (!mounted.current) return;
        setRead({
          kind: "ready",
          entries: [...shown.entries, ...entries],
          capped,
          years: shown.years + 1,
          more: entries.length > 0 ? "idle" : "empty",
        });
      },
      () => {
        if (mounted.current) setRead({ ...shown, more: "failed" });
      },
    );
  }

  const labels = tagLabelsFor(t.dateLocale);
  const names = tags.map((slug) => tagLabelOf(slug, vocabulary));
  return (
    <section className="journal-tagged" aria-label={t.taggedEntries}>
      <p className="journal-muted">
        {labels.filtered(names)} ·{" "}
        {t.taggedWindow(read.kind === "ready" ? read.years : 1)}
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
        <EmptyState title={t.taggedEmpty(tags.length)} />
      )}
      {read.kind === "ready" && read.entries.length > 0 && (
        <ul className="journal-timeline">
          {read.entries.map((entry) => (
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
      {read.kind === "ready" && read.capped && (
        <p className="journal-muted" role="status">
          {t.taggedCapped(read.entries.length)}
        </p>
      )}
      {read.kind === "ready" && read.more === "empty" && (
        <p className="journal-muted" role="status">
          {t.taggedNoOlder}
        </p>
      )}
      {read.kind === "ready" && read.more === "busy" && (
        <p role="status">{t.loading}</p>
      )}
      {read.kind === "ready" && read.more === "failed" && (
        <ErrorNotice locale={t.dateLocale} onRetry={readOlder} />
      )}
      {/* The 12 months before the oldest read; none once a window was cut at the page limit. */}
      {read.kind === "ready" && !read.capped && read.more !== "failed" && (
        <p>
          <button
            type="button"
            className="sk-btn--quiet"
            disabled={read.more === "busy"}
            onClick={readOlder}
          >
            {t.taggedMore}
          </button>
        </p>
      )}
    </section>
  );
}
