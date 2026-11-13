import { useEffect, useId, useState } from "react";
import { shiftDate } from "./dates";
import { EntryRow } from "./entry-row";
import type { JournalLabels } from "./labels";
import type { JournalEntry, JournalTransport } from "./transport";
import { EmptyState, ErrorNotice } from "../mcp-apps/ui/states";
import { tagLabelsFor } from "../mcp-apps/ui/tag-labels";
import { tagLabelOf, type TagOption } from "../mcp-apps/ui/tag-vocabulary";

/** list_journal_entries takes at most 366 inclusive days: today and the 365 before it. */
const WINDOW_DAYS = 365;
/** Pages of 50 followed for one list, so a list holds at most 500 entries. */
const PAGE_LIMIT = 10;

type Read =
  | { kind: "loading" }
  | { kind: "ready"; entries: JournalEntry[]; capped: boolean }
  | { kind: "error"; cause: unknown };

/**
 * The entries that carry every chosen tag, from the last 12 months, newest first. The server lists them oldest first and
 * cannot turn the order round, so the pages are followed to the end and reversed here. A list that runs past the page limit
 * shows its oldest entries and says so. A new `refreshKey` reads again in place, without the loading line.
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
  const headingId = useId();
  const list = transport.listTaggedEntries;
  useEffect(() => {
    if (!list) return;
    let current = true;
    const from = shiftDate(today, -WINDOW_DAYS);
    void (async () => {
      const entries: JournalEntry[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < PAGE_LIMIT; page++) {
        const got = await list(tags, from, today, cursor);
        entries.push(...got.entries);
        cursor = got.next_cursor;
        if (!cursor) break;
      }
      return { entries, capped: cursor !== null };
    })().then(
      ({ entries, capped }) => {
        if (current)
          setRead({ kind: "ready", entries: entries.reverse(), capped });
      },
      (cause: unknown) => {
        if (current) setRead({ kind: "error", cause });
      },
    );
    return () => {
      current = false;
    };
  }, [list, tags, today, attempt, refreshKey]);

  const labels = tagLabelsFor(t.dateLocale);
  const names = tags.map((slug) => tagLabelOf(slug, vocabulary));
  return (
    <section className="journal-tagged" aria-labelledby={headingId}>
      <h3 id={headingId}>{t.taggedEntries}</h3>
      <p className="journal-muted">
        {labels.filtered(names)} · {t.taggedWindow}
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
    </section>
  );
}
