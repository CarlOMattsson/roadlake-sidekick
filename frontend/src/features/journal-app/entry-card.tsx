import { Fragment, type ReactNode } from "react";
import { formatShortDateWithYear, formatTime, relativeDay } from "./dates";
import type { JournalLabels } from "./labels";
import type { JournalEntryLink } from "./transport";
import { CardFoot } from "../mcp-apps/ui/card";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import { TagChips } from "../mcp-apps/ui/tags";
import "./journal.css";

/**
 * What the compact card shows of one entry. The link fields are present only when the tool result
 * carries them, so the card never claims a count or a name it does not know.
 */
export type EntryCardData = {
  id: string;
  title: string;
  summary: string | null;
  /** The entry's source. The card does not read it: the original text is shown in fullscreen only. */
  source_id?: string;
  /** The day the entry belongs to, shown in the saved line when the result carries it. */
  journal_date?: string;
  /** The time of the entry, shown in the saved line when the result carries it. */
  occurred_at?: string | null;
  contact_ids?: string[];
  task_ids?: string[];
  /** The entry's tags (slugs); absent from a result of an older server. */
  tags?: string[];
  /** The entry's version: the expected_version of the link writes; without it the card cannot remove links. */
  version?: number;
  /** The Projects and Contacts of the entry with their names; absent from a result of an older server. */
  links?: JournalEntryLink[];
};

/** How many linked names the card names; the rest are counted ("och 1 till"). */
const CARD_LINK_LIMIT = 3;

/** The name of a linked Project or Contact: its label, or the kind's fallback when the label is null. */
export function linkName(link: JournalEntryLink, t: JournalLabels): string {
  if (link.label) return link.label;
  return link.kind === "contact"
    ? t.linkContactFallback
    : t.linkProjectFallback;
}

/**
 * Compact card for one Journal entry (designsystem §3, Inline-kort): the kicker "Dagbok · sparad 10:20", the title,
 * the summary clamped by CSS, one muted line "Sammanfattad av Claude · Kopplad till Bo Berg", and the text button
 * "Öppna anteckningen ›" (no ink: opening is navigation) that opens the entry view. The original text is read in
 * fullscreen only, not here. The links are text (no × in the card, it was easy to hit by
 * mistake); a link is removed in the entry's fullscreen view. A contact's name opens the contact when the host passes
 * `onOpenContact`. The card reads nothing.
 */
export function EntryCard({
  entry,
  today,
  labels: t,
  onOpen,
  opening = false,
  onOpenContact,
}: {
  entry: EntryCardData;
  /** Today, YYYY-MM-DD, so the saved line can say "igår" or leave the day out for today. Passed in, never read here. */
  today: string;
  labels: JournalLabels;
  onOpen: () => void;
  /** True while the host answers the fullscreen request; the button is busy and cannot be pressed. */
  opening?: boolean;
  /** Opens a linked Contact in fullscreen. Absent: a contact name is plain text. */
  onOpenContact?: (link: JournalEntryLink) => void;
}) {
  const summary = summaryRest(entry.title, entry.summary);
  const meta = [
    entry.summary?.trim() ? t.cardSummarized : undefined,
    ...(entry.links === undefined
      ? legacyLinks(entry, t)
      : linkParts(entry, t, onOpenContact)),
    // The tags close the same line (two at most, "+N" for the rest), so the card stays as high as without them.
    entry.tags && entry.tags.length > 0 ? (
      <TagChips tags={entry.tags} max={2} locale={t.dateLocale} />
    ) : undefined,
  ].filter((part) => part !== undefined);
  return (
    <section className="sidekick-journal" aria-label={t.title}>
      <article className="journal-card sk-card">
        {/* The kicker before the title: "Dagbok · idag 10:20". Two elements, so the app name stays a heading and the
            day line stays a status. */}
        <div className="journal-card-meta">
          <h1 className="sk-eyebrow">{t.title}</h1>
          <span aria-hidden="true">·</span>
          <p role="status">{savedLine(entry, t, today)}</p>
        </div>
        <h2 className="sk-card__title" tabIndex={-1}>
          {entry.title}
        </h2>
        {summary && (
          <p className="journal-summary journal-card-summary">{summary}</p>
        )}
        {/* One muted line: "Sammanfattad av Claude · Kopplad till Bo Berg · 1 uppgift · viktig". */}
        {meta.length > 0 && (
          <p className="sk-card__meta journal-card-links">
            {/* "·" leads its part, so a narrow card breaks before a "·", never inside a name; a part that starts a
                line has its "·" clipped away (journal.css). */}
            {meta.map((part, index) => (
              <Fragment key={index}>
                {index > 0 ? " " : null}
                <span>
                  {index > 0 ? (
                    <span className="journal-card-sep">· </span>
                  ) : null}
                  {part}
                </span>
              </Fragment>
            ))}
          </p>
        )}
        {/* The open button is the foot's own child, as in the shopping card: inside a wrapper that the foot lets
            shrink, "Öppna anteckningen" broke onto two lines beside the coin. */}
        <CardFoot>
          <button
            type="button"
            className="sk-btn--open"
            onClick={onOpen}
            disabled={opening}
            aria-busy={opening || undefined}
          >
            {opening ? t.cardOpening : t.cardOpenEntry}
            <ChevronRightIcon />
          </button>
        </CardFoot>
      </article>
    </section>
  );
}

/**
 * The line above a saved original. Claude's summary is named only when the entry has one; an entry
 * without a summary says only that the original is saved.
 */
export function originalLine(
  summary: string | null | undefined,
  t: JournalLabels,
): string {
  return summary?.trim() ? t.summarizedNote : t.originalSavedNote;
}

/** A result without link names: the counts as before. */
function legacyLinks(entry: EntryCardData, t: JournalLabels): string[] {
  const contacts = entry.contact_ids?.length;
  const tasks = entry.task_ids?.length;
  if (contacts === 0 && tasks === 0) return [t.cardNoLinks];
  const parts: string[] = [];
  if (contacts !== undefined) parts.push(t.cardContacts(contacts));
  if (tasks !== undefined) parts.push(t.cardTasks(tasks));
  return parts;
}

/**
 * The links as parts of the meta line: "Kopplad till Bo Berg, Anna Andersson och 1 till", then "1 uppgift". A
 * contact's name is a text button that opens the contact when the host can; a project's name is plain text. No
 * remove button: a link is removed in the entry's fullscreen view. Tasks are not links in the record, so they
 * show as a count.
 */
function linkParts(
  entry: EntryCardData,
  t: JournalLabels,
  onOpenContact?: (link: JournalEntryLink) => void,
): ReactNode[] {
  const links = entry.links ?? [];
  const tasks = entry.task_ids?.length ?? 0;
  if (links.length === 0 && tasks === 0) return [t.cardNoLinks];
  const shown = links.slice(0, CARD_LINK_LIMIT);
  const rest = links.length - shown.length;
  const parts: ReactNode[] = [];
  if (links.length > 0)
    parts.push(
      <>
        {t.linkedTo}{" "}
        {shown.map((link, index) => {
          const name = linkName(link, t);
          const separator =
            index === 0
              ? ""
              : index === shown.length - 1 && rest === 0
                ? ` ${t.and} `
                : ", ";
          return (
            <span key={`${link.kind}:${link.id}`}>
              {separator}
              {onOpenContact && link.kind === "contact" ? (
                <button
                  type="button"
                  className="journal-link-name"
                  onClick={() => onOpenContact(link)}
                >
                  {name}
                </button>
              ) : (
                <span className="journal-link-name">{name}</span>
              )}
            </span>
          );
        })}
        {rest > 0 && ` ${t.and} ${t.andMoreCount(rest)}`}
      </>,
    );
  if (tasks > 0) parts.push(t.cardTasks(tasks));
  return parts;
}

/** Separators a summary may put between the title and the rest of its text, such as "Möte: ...". */
const TITLE_SEPARATORS = /^[\s\p{P}\p{S}]+/u;

/**
 * The summary as the card shows it. A summary that repeats the title (ignoring case) shows nothing;
 * one that starts with the title shows only the rest. A title that is only the start of a longer
 * word ("Möte" in "Mötesanteckningar") does not count as a start.
 */
export function summaryRest(
  title: string,
  summary: string | null,
): string | undefined {
  const heading = title.trim();
  const text = summary?.trim() ?? "";
  if (text === "") return undefined;
  if (heading === "") return text;
  // Lower-casing can change the length of some characters, so the comparison uses the original string.
  const head = text.slice(0, heading.length);
  if (head.toLocaleLowerCase("sv") !== heading.toLocaleLowerCase("sv")) {
    return text;
  }
  const after = text.slice(heading.length);
  if (after === "") return undefined;
  if (!/^[\s\p{P}\p{S}]/u.test(after)) return text;
  const rest = after.replace(TITLE_SEPARATORS, "");
  return rest === "" ? undefined : rest;
}

/**
 * When the entry happened, the day and time it is filed under: "idag 12:30", "igår 18:05", or "26 okt 14:05"
 * (the year only when it is not this year's). It is not when the entry was saved, so the line does not say
 * "sparad" then; a result without a date says only "sparad".
 */
function savedLine(
  entry: EntryCardData,
  t: JournalLabels,
  today: string,
): string {
  if (!entry.journal_date) return t.cardSaved;
  const time = entry.occurred_at
    ? formatTime(entry.occurred_at, t.dateLocale)
    : undefined;
  const relative = relativeDay(entry.journal_date, today);
  if (relative === "today") return t.cardWhenToday(time);
  if (relative === "yesterday") return t.cardWhenYesterday(time);
  return t.cardWhenAt(
    formatShortDateWithYear(entry.journal_date, t.dateLocale, today),
    time,
  );
}
