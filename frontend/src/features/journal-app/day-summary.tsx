import type { JournalLabels } from "./labels";
import type { JournalDay, JournalDaySummary } from "./transport";

/** The summary section shows with a summary or a note about one; an empty summary is not shown. */
export function hasDaySummary(summary: JournalDaySummary): boolean {
  return (
    Boolean(summary.exists && summary.content?.overview) ||
    summary.status === "stale" ||
    summary.status === "failed"
  );
}

/**
 * The day's summary. It has no heading: the summary is an ingress under the strip. A muted label in the section type
 * names it, so it is not read as the user's own note; assistive technology hears the name as the section's.
 */
export function DaySummary({
  day: { summary },
  fullscreen,
  labels: t,
}: {
  day: JournalDay;
  fullscreen: boolean;
  labels: JournalLabels;
}) {
  if (!hasDaySummary(summary)) return null;
  const overview = summary.exists ? summary.content?.overview : undefined;
  return (
    <section className="journal-day-summary" aria-label={t.summary}>
      {overview && (
        <p className="journal-summary-label" aria-hidden="true">
          {t.summary}
        </p>
      )}
      {overview && (
        <p
          className={
            fullscreen
              ? "journal-summary"
              : "journal-summary journal-card-summary"
          }
        >
          {overview}
        </p>
      )}
      {summary.status === "stale" && <p>{t.summaryStale}</p>}
      {summary.status === "failed" && <p>{t.summaryFailed}</p>}
    </section>
  );
}
