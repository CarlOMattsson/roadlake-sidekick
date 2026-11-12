import { Fragment } from "react";
import { type DueLocale, workDate } from "../mcp-apps/ui/due";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import type { AgendaUndo } from "./agenda-undo";
import type { WorkLabels } from "./labels";
import type { WorkAgendaPage, WorkFilters, WorkItemRecord } from "./transport";
import {
  LONG_WAIT_DAYS,
  isWaitingFilter,
  waitingLabelsFor,
  waitingRows,
} from "./waiting";
import { cardKey, groupAgenda, hiddenRows } from "./work-items";
import {
  InlineRow,
  ListSummary,
  inlineMeta,
  statusLabel,
  type InlineSummaryNotice,
} from "./inline-summary-list";

/** At most this many agenda records are listed inline: overdue first, then today. */
const AGENDA_ROWS = 4;
/** The agenda card lists at most three records (designsystem §3: an inline card's body has at most three rows). */
const AGENDA_CARD_ROWS = 3;

/**
 * What the inline agenda needs to mark a Task done, as the fullscreen agenda does: the fullscreen labels
 * for the glyph and the Undo line, the busy state of the write, the Undo line of the last change and the
 * notice of a failed write. Without it the rows are text only.
 */
export type InlineAgendaWrite = {
  work: WorkLabels;
  /** A write runs: the glyphs are off and the Undo line says "Moving…". */
  busy: boolean;
  /** The glyph of a row: marks a Task done, or not done again. */
  onToggle: (item: WorkItemRecord) => void;
  /** The last status change, undone with "Undo" for a while; absent after it expires. */
  undo?: AgendaUndo;
  onUndo: () => void;
  onUndoExpire: () => void;
  notice?: InlineSummaryNotice;
};

/**
 * Inline agenda (designsystem §3, inline card): the kicker "Arbete · ons 4 nov", the counts as the title in the
 * rows' order ("1 idag, 2 försenade"), then at most three rows, today first and then overdue. No headings and no status glyphs: a row is the title and its due words ("Ring Anna om offerten ·
 * 5 dagar försenad", red when overdue), and the whole row opens its record (`onOpenItem`; without it, the agenda).
 * With nothing overdue or due today the title is "Agenda" over one sentence. "Öppna agendan" shows the rest.
 */
export function AgendaSummary({
  page,
  filters,
  labels,
  onOpen,
  onOpenItem,
}: {
  page: WorkAgendaPage;
  /** The filters the agenda was read with; waiting=waiting turns the card into the waiting view. */
  filters?: WorkFilters;
  labels: InlineSummaryLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
  /** Opens one record from its row, in fullscreen; without it a row opens the agenda. */
  onOpenItem?: (item: WorkItemRecord) => void;
  /** Accepted for the caller's sake but unused: the card has no status glyphs and writes nothing. */
  write?: InlineAgendaWrite;
}) {
  if (isWaitingFilter(filters))
    return <WaitingSummary page={page} labels={labels} onOpen={onOpen} />;
  return (
    <DatedAgendaSummary
      page={page}
      labels={labels}
      onOpen={onOpen}
      onOpenItem={onOpenItem}
    />
  );
}
/**
 * Inline waiting view: who each Task waits on and for how long, the longest wait first, as text rows
 * ("Anna Berg · 9 dagar", then the Task). Like every inline list it is read-only: "Open" shows the
 * fullscreen view, where each row has its "Påminn" button.
 */
function WaitingSummary({
  page,
  labels,
  onOpen,
}: {
  page: WorkAgendaPage;
  labels: InlineSummaryLabels;
  onOpen: () => void;
}) {
  const words = waitingLabelsFor(labels.dateLocale);
  const rows = waitingRows(page.items, new Date());
  const shown = rows.slice(0, AGENDA_ROWS);
  const more = page.next_cursor !== null;
  return (
    <ListSummary
      labels={labels}
      kindLabel={words.kind}
      lines={[
        {
          key: "waiting",
          label: words.kind,
          count: rows.length,
          more,
          text: words.count(rows.length, more),
        },
      ]}
      empty={rows.length === 0 && !more ? words.empty : undefined}
      onOpen={onOpen}
      openLabel={labels.showAll(rows.length, more)}
    >
      {shown.length > 0 ? (
        <ul className="work-compact-rows">
          {shown.map(({ item, who, days }) => (
            <li key={cardKey(item)} className="work-compact-row">
              <span className="work-compact-row-title">
                {`${who ?? words.someone} · ${words.days(days)}`}
              </span>
              <span
                className="work-compact-status"
                data-tone={
                  days !== null && days >= LONG_WAIT_DAYS
                    ? "overdue"
                    : undefined
                }
              >
                {item.title}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {rows.length > shown.length ? (
        <p className="work-compact-more">{`+${rows.length - shown.length}`}</p>
      ) : null}
    </ListSummary>
  );
}

/** Priority rank in the agenda order: urgent, high, normal, low. A missing or unknown value counts as normal. */
function priorityRank(priority: string | null | undefined): number {
  switch (priority) {
    case "urgent":
      return 3;
    case "high":
      return 2;
    case "low":
      return 0;
    default:
      return 1;
  }
}

/** The due instant in milliseconds; a record without a readable date sorts last. */
function dueTime(item: WorkItemRecord): number {
  const time = item.due_at ? Date.parse(item.due_at) : Number.NaN;
  return Number.isNaN(time) ? Number.MAX_SAFE_INTEGER : time;
}

/**
 * The agenda order inside a group, for its rows and for the record the card starts with: higher priority
 * first, then the oldest due date first.
 */
function compareAgenda(a: WorkItemRecord, b: WorkItemRecord): number {
  const byPriority = priorityRank(b.priority) - priorityRank(a.priority);
  return byPriority !== 0 ? byPriority : dueTime(a) - dueTime(b);
}

/** The overdue group: the oldest due date first, everywhere (A4); priority does not reorder it. */
function compareOverdue(a: WorkItemRecord, b: WorkItemRecord): number {
  return dueTime(a) - dueTime(b);
}

function DatedAgendaSummary({
  page,
  labels,
  onOpen,
  onOpenItem,
}: {
  page: WorkAgendaPage;
  labels: InlineSummaryLabels;
  onOpen: () => void;
  onOpenItem?: (item: WorkItemRecord) => void;
}) {
  // Read on every render, as the fullscreen agenda does, so the due days match the board after
  // midnight (a frozen clock from mount made the card count one day less).
  const now = new Date();
  const locale: DueLocale = labels.dateLocale.startsWith("sv") ? "sv" : "en";
  const sections = groupAgenda(page.items);
  const groupOf = (
    group: string,
    compare: (a: WorkItemRecord, b: WorkItemRecord) => number,
  ) =>
    [
      ...(sections.find((section) => section.group === group)?.items ?? []),
    ].sort(compare);
  const overdue = groupOf("overdue", compareOverdue);
  const today = groupOf("today", compareAgenda);
  // Every group that is neither overdue nor today, counted; a null group (no groups sent) is not counted.
  const hidden = sections
    .filter(
      (section) =>
        section.group !== null &&
        section.group !== "overdue" &&
        section.group !== "today",
    )
    .reduce((total, section) => total + section.items.length, 0);
  const more = page.next_cursor !== null;
  const listed = overdue.length + today.length;
  // The card answers "today" first: with a Task due today the first row is today's, then the oldest overdue (the title once said
  // "1 idag" over three overdue rows).
  const rows = (
    today.length > 0 ? [today[0]!, ...overdue, ...today.slice(1)] : overdue
  ).slice(0, AGENDA_CARD_ROWS);
  const shownToday = rows.filter((row) => today.includes(row)).length;
  // What the rows leave out of the Agenda the foot opens, every group of it ("3 fler" read against the
  // Agenda's 10 rows). With another page to read the count is a floor: "7+ fler". The fullscreen Agenda lists every record of the page.
  const hiddenText = labels.agendaHidden(
    hiddenRows(page.items.length, rows.length),
    more,
  );
  return (
    <ListSummary
      labels={labels}
      kindLabel={labels.kind.agenda}
      kicker={`${labels.appName} · ${workDate(now.toISOString(), now, locale, { inline: true, relative: false })}`}
      className="work-compact-agenda"
      lines={
        listed > 0
          ? [
              {
                key: "counts",
                label: "",
                count: listed,
                more,
                text: labels.agendaTitle(overdue.length, today.length, more),
              },
            ]
          : []
      }
      empty={listed === 0 ? labels.agendaEmpty : undefined}
      // Without an Open button when there is nothing to open: the empty sentence stands alone.
      onOpen={listed + hidden > 0 || more ? onOpen : undefined}
      openLabel={labels.openAgenda}
      aside={rows.length > 0 ? hiddenText : undefined}
    >
      {rows.length > 0 ? (
        // Every row of today's, then "Försenade" before the first overdue row: the two groups have a
        // border. The rows are drawn by their own group: which rows are chosen is above (today's first
        // row, then the overdue), but a second row of today's never stands under the "Försenade" label. Without a row
        // of today's the card's title already says what the rows are, and the label is left out.
        (shownToday > 0 && overdue.length > 0
          ? [
              rows.filter((row) => today.includes(row)),
              rows.filter((row) => overdue.includes(row)),
            ]
          : [rows]
        )
          .filter((part) => part.length > 0)
          .map((part, at) => (
            <Fragment key={at}>
              {at > 0 && (
                <p className="work-compact-group">
                  {labels.agendaOverdueLabel}
                </p>
              )}
              <ul className="work-compact-rows">
                {part.map((item) => (
                  <AgendaRow
                    key={cardKey(item)}
                    item={item}
                    now={now}
                    labels={labels}
                    onOpen={() => (onOpenItem ? onOpenItem(item) : onOpen())}
                  />
                ))}
              </ul>
            </Fragment>
          ))
      ) : hidden > 0 || more ? (
        <p className="sk-card__meta">{labels.agendaRest(hidden, more)}</p>
      ) : null}
    </ListSummary>
  );
}

/** One row of the inline agenda: the title, and its meta under it. */
function AgendaRow({
  item,
  now,
  labels,
  onOpen,
}: {
  item: WorkItemRecord;
  now: Date;
  labels: InlineSummaryLabels;
  onOpen: () => void;
}) {
  return (
    <InlineRow
      title={item.title}
      meta={inlineMeta(item, now, labels.dateLocale, (s) =>
        statusLabel(labels, "task", s),
      )}
      onOpen={onOpen}
    />
  );
}
