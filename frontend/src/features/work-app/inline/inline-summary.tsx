import { Fragment, useContext, useEffect, useId } from "react";
import {
  type DueLocale,
  type DueTone,
  dueClockText,
  relativeDue,
  workDate,
} from "../../mcp-apps/ui/due";
import { Progress } from "../../mcp-apps/ui/progress";
import "./inline-summary.css";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { Card } from "../../mcp-apps/ui/card";
import { OpenLink } from "../../mcp-apps/ui/open-link";
import { ReceiptBar, type ReceiptState } from "../../mcp-apps/ui/receipt";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { TagChips } from "../../mcp-apps/ui/tags";
import { KnownTags } from "../shared/work-tags";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import {
  InlineRow,
  ListSummary,
  NoticeRow,
  statusLabel,
  type InlineSummaryKind,
  type InlineSummaryNotice,
} from "./inline-summary-list";

// The public surface of the inline cards stays here; the agenda, hierarchy and shared list parts live in siblings.
export { AgendaSummary, type InlineAgendaWrite } from "./inline-agenda-summary";
export { HierarchySummary } from "./inline-hierarchy-summary";
export {
  InlineEmpty,
  InlineRow,
  inlineMeta,
  type InlineMetaPart,
  type InlineSummaryKind,
  type InlineSummaryNotice,
} from "./inline-summary-list";

/** At most this many Contact names are listed inline. */
const CONTACT_ROWS = 3;

/**
 * The datapoints the summary may show. Each is optional. `steps` is drawn as a progress count
 * (done/total with a thin bar); `contacts` is a count in the meta line. For a Task,
 * `steps` counts its Steps; for a Project, `tasks` is its progress.
 */
export type InlineSummaryDatapoints = {
  steps?: { done: number; total: number };
  contacts?: number;
  /** A Project's Tasks as progress: done of total, shown as "3 of 12 tasks done". */
  tasks?: { done: number; total: number };
  /** A Project's overdue Tasks, shown as "2 overdue" when above zero. */
  overdue?: number;
};

export type InlineSummaryData = {
  kind: InlineSummaryKind;
  /** Rendered as text; a title is data, never markup. */
  title: string;
  /** The raw status value; translated with the labels, and shown as it arrived if unknown. */
  status: string;
  /** An instant (Task due_at) or a calendar date (YYYY-MM-DD, Project target_date). */
  dueDate?: string | null;
  /** The record's version, so the Done action writes against the version the summary shows (Task only). */
  version?: number;
  datapoints?: InlineSummaryDatapoints;
  /** A recurring Task's completion on record before this write; Undo writes it back with the due date. */
  lastCompletedAt?: string | null;
  /** A Task's priority; only "high" and "urgent" are shown, as words. */
  priority?: string | null;
  /** A Task's description: one line, cut with an ellipsis. Absent or empty means no line. */
  description?: string | null;
  /** The name of the Task's Project, when the record carries it. */
  projectTitle?: string | null;
  /** The record's tag slugs; two are shown with "+N" for the rest. Absent or empty means no line. */
  tags?: readonly string[];
  /** The Task is marked as possible with AI; its plan may then wait for the owner's approval. */
  aiPossible?: boolean;
};

/**
 * The inline summary, in the family's `Card`. Loading, empty and error come in through `state`; the ready state takes
 * the record and its actions: "Done" (a Task only, given by `onComplete`, the primary action; `busy` disables it while
 * the write runs) and the card's one main link (`OpenLink`, last: it asks the host for fullscreen). The card shows the
 * Task's new state ("Done" in its status line) with no Undo of its own: Done's receipt, with Ångra, is the bar of
 * `receipt` at the card's foot. A `notice` shows a write's conflict or failure. The summary has no inner scroll and no
 * menus.
 */
export type InlineSummaryProps =
  | { state: "loading"; labels: InlineSummaryLabels }
  | { state: "empty"; labels: InlineSummaryLabels }
  | {
      /** The record was read and is gone (not_found): one calm line, no retry, since it cannot come back. */
      state: "gone";
      labels: InlineSummaryLabels;
      /** The overrubrik: the kind of record that is gone. */
      kindLabel: string;
      /** Which "…no longer exists" line says what is gone: the Task, the Project or the Contact. */
      goneKey: "goneTask" | "goneProject" | "goneContact";
    }
  | {
      state: "error";
      labels: InlineSummaryLabels;
      /** The overrubrik: the kind of record that could not be read. */
      kindLabel: string;
      /** What could not be read ("work:task"), for the notice's heading; the card's `kindLabel` says it above. */
      subject: string;
      /** The failure, when the caller has it: decides the notice's second line. */
      cause?: unknown;
      onRetry?: () => void;
    }
  | {
      state: "ready";
      labels: InlineSummaryLabels;
      summary: InlineSummaryData;
      onOpen?: () => void;
      onComplete?: () => void;
      busy?: boolean;
      /** The card's receipt bar (Done's receipt with Ångra); the card shows it last. Absent: no bar. */
      receipt?: ReceiptState;
      /** Moves focus to Done when it appears (after Undo, so focus stays on a control that is still there). */
      focusComplete?: boolean;
      /** Done took the Done button away: focus, if it fell to the page, goes to the card's open link. */
      focusOpen?: boolean;
      notice?: InlineSummaryNotice;
      /** A Task whose AI plan waits for the owner: the line that says so and the text of the button that opens the Task. */
      plan?: { line: string; reviewLabel: string };
    };

/** Puts focus on a button when it mounts, so a control that replaces the one that had focus keeps it. */
function focusOnMount(button: HTMLButtonElement | null) {
  button?.focus();
}

/** One line of a Task's description: whitespace collapsed, cut at `max` characters with an ellipsis. */
export function oneLine(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

/** Puts focus on the card's open link when the control that had it is gone and focus fell to the page. */
function focusOpenLink(cardId: string) {
  const active = document.activeElement;
  if (active && active !== document.body) return;
  document
    .getElementById(cardId)
    ?.querySelector<HTMLElement>(".sk-open-link")
    ?.focus();
}

export function InlineSummary(props: InlineSummaryProps) {
  const { labels } = props;
  const known = useContext(KnownTags);
  const cardId = useId();
  // Done takes its button away: focus never falls to the page, it goes to the link that stays.
  const focusOpen = props.state === "ready" && props.focusOpen;
  useEffect(() => {
    if (focusOpen) focusOpenLink(cardId);
  }, [focusOpen, cardId]);

  if (props.state === "loading") {
    return (
      <Card className="work-compact-card" eyebrow={labels.appName}>
        <div className="work-compact-loading" aria-busy="true">
          <p role="status" className="work-compact-status">
            {labels.loading}
          </p>
          <span className="work-compact-skeleton" aria-hidden="true" />
          <span
            className="work-compact-skeleton work-compact-skeleton-short"
            aria-hidden="true"
          />
        </div>
      </Card>
    );
  }

  if (props.state === "empty") {
    return (
      <Card className="work-compact-card" eyebrow={labels.appName}>
        <p className="work-compact-status">{labels.empty}</p>
      </Card>
    );
  }

  if (props.state === "gone") {
    return (
      <Card
        className="work-compact-card"
        eyebrow={`${labels.appName} · ${props.kindLabel}`}
      >
        <p role="status" className="work-compact-status">
          {labels[props.goneKey]}
        </p>
      </Card>
    );
  }

  if (props.state === "error") {
    return (
      <Card
        className="work-compact-card"
        eyebrow={`${labels.appName} · ${props.kindLabel}`}
      >
        <ErrorNotice
          locale={labels.dateLocale}
          subject={props.subject}
          cause={props.cause}
          onRetry={props.onRetry}
        />
      </Card>
    );
  }

  const {
    summary,
    onOpen,
    onComplete,
    busy,
    receipt,
    focusComplete,
    notice,
    plan,
  } = props;
  // A plan that waits for review makes "Granska planen" (which opens the Task) the primary; Done stays beside it.
  const review = plan && onOpen ? plan : undefined;
  const locale: DueLocale = labels.dateLocale.startsWith("sv") ? "sv" : "en";
  const meta = metaParts(summary, labels, locale, new Date());
  const steps = summary.datapoints?.steps;
  // Project and priority share one line; a line with neither is left out.
  const head = [
    summary.projectTitle,
    priorityText(labels, summary.priority),
  ].filter((part): part is string => Boolean(part));
  const description = summary.description?.trim()
    ? oneLine(summary.description)
    : null;
  // Done is the primary action of a Task that can be marked done. Open is navigation, so it is the card's main
  // link (`OpenLink`, designsystem §3), last in the card, never beside Done.
  const openText =
    summary.kind === "project" ? labels.showProject : labels.showTask;

  return (
    <Card
      id={cardId}
      className="work-compact-card"
      aria-label={kindLabel(labels, summary.kind)}
      eyebrow={`${labels.appName} · ${kindLabel(labels, summary.kind)}`}
      title={summary.title}
    >
      <p>
        <span className="work-chip">
          {/* The ring says only done or not done (designsystem §3.3), and an empty ring in front of `in_progress` reads
              as a radio button: a known open status is told by its word alone. */}
          {showsGlyph(labels, summary) ? (
            <StatusGlyph kind={summary.kind} status={summary.status} />
          ) : null}
          {statusLabel(labels, summary.kind, summary.status)}
        </span>
      </p>
      {meta.length > 0 ? (
        <p className="work-compact-status">
          {meta.map((part, index) => (
            <Fragment key={part.key}>
              {index > 0 ? " · " : null}
              <span data-tone={part.tone}>{part.text}</span>
            </Fragment>
          ))}
        </p>
      ) : null}
      {head.length > 0 ? (
        <p className="work-compact-status">{head.join(" · ")}</p>
      ) : null}
      {/* Two tags and "+N" with the other metadata; no line when the record has none. */}
      {summary.tags && summary.tags.length > 0 ? (
        <p className="work-compact-status work-compact-tags">
          <TagChips
            tags={summary.tags}
            known={known}
            max={2}
            locale={labels.dateLocale}
          />
        </p>
      ) : null}
      {steps ? (
        <p className="work-compact-status">
          <Progress
            done={steps.done}
            total={steps.total}
            label={labels.stepsOf(steps.done, steps.total)}
          />
        </p>
      ) : null}
      {description ? (
        <p className="work-compact-status work-compact-description">
          {description}
        </p>
      ) : null}
      {plan ? <p className="work-compact-status">{plan.line}</p> : null}
      {review || onComplete ? (
        <div className="work-compact-actions">
          {review ? (
            <button
              type="button"
              className="work-compact-action sk-btn--primary"
              onClick={onOpen}
            >
              {review.reviewLabel}
            </button>
          ) : null}
          {onComplete ? (
            <button
              type="button"
              className={
                review
                  ? "work-compact-action sk-btn--secondary"
                  : "work-compact-action sk-btn--primary"
              }
              onClick={onComplete}
              disabled={busy}
              aria-busy={busy || undefined}
              ref={focusComplete ? focusOnMount : undefined}
            >
              {busy ? labels.completing : labels.complete}
            </button>
          ) : null}
        </div>
      ) : null}
      {/* A failed write stays a row under the control that made it; the receipt of a done one is the bar below. */}
      {notice ? <NoticeRow notice={notice} locale={labels.dateLocale} /> : null}
      {/* A Task whose plan waits for review opens through "Granska planen", the primary above: its way in is that
          button, so the card does not carry a second one to the same place. */}
      {onOpen && !review ? <OpenLink label={openText} onOpen={onOpen} /> : null}
      {receipt ? <ReceiptBar receipt={receipt} /> : null}
    </Card>
  );
}

/** A matching Contact as the inline list shows it: its id keys the row, its name is the text. */
export type ContactName = { id: string; name: string };

/**
 * Inline Contact list: how many Contacts match, counted on the page read so far, then the first
 * three names; with no Contact at all the card is the room's empty state. `more` marks a page with a next cursor, so the count is shown with "+". A name equal
 * to `query` (ignoring case and surrounding spaces) is listed first; the rest keep the order read.
 */
export function ContactsSummary({
  count,
  more,
  contacts = [],
  query = "",
  labels,
  onOpen,
  onOpenContact,
}: {
  count: number;
  more: boolean;
  contacts?: ContactName[];
  query?: string;
  labels: InlineSummaryLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
  /** Opens one Contact from its row, in fullscreen; without it the names are plain text. */
  onOpenContact?: (contact: ContactName) => void;
}) {
  const wanted = query.trim().toLocaleLowerCase();
  const isExact = (contact: ContactName) =>
    wanted !== "" && contact.name.trim().toLocaleLowerCase() === wanted;
  // Array.prototype.sort is stable, so only the exact matches move, to the front.
  const shown = [...contacts]
    .sort((a, b) => Number(isExact(b)) - Number(isExact(a)))
    .slice(0, CONTACT_ROWS);
  // No Contact at all: the room's empty state; a search with no match says so and offers no example.
  const blank =
    count === 0 && !more
      ? wanted === ""
        ? labels.blank.contacts
        : { title: labels.noContactMatches(query.trim()) }
      : undefined;
  return (
    <ListSummary
      labels={labels}
      kindLabel={labels.kind.contacts}
      className={onOpenContact ? "work-compact-opens" : undefined}
      lines={[
        {
          key: "matches",
          label: labels.matchCount,
          count,
          more,
          // Without a search the list is every Contact, so the count is plain text, not "Matches".
          text: wanted === "" ? labels.contactCount(count, more) : undefined,
        },
      ]}
      blank={blank}
      onOpen={onOpen}
      openLabel={labels.openContacts}
      more={labels.moreRows(count - shown.length, more)}
    >
      {shown.length > 0 ? (
        <ul className="work-compact-rows">
          {shown.map((contact) =>
            onOpenContact ? (
              <InlineRow
                key={contact.id}
                title={contact.name}
                meta={[]}
                onOpen={() => onOpenContact(contact)}
              />
            ) : (
              <li key={contact.id} className="work-compact-row">
                <span className="work-compact-row-title">{contact.name}</span>
              </li>
            ),
          )}
        </ul>
      ) : null}
    </ListSummary>
  );
}

type MetaPart = { key: string; text: string; tone?: DueTone };

/**
 * The meta line: due, then a Project's progress and overdue count, then contacts, joined by " · " in that order. A relative due
 * date comes from relativeDue (owner calendar day, given `now`); an overdue text already
 * says so, so it is shown alone and every other due text gets the "Due" label in front, and the Task's clock time
 * after the date when it has one ("Due today 5:30 pm").
 */
function metaParts(
  summary: InlineSummaryData,
  labels: InlineSummaryLabels,
  locale: DueLocale,
  now: Date,
): MetaPart[] {
  const parts: MetaPart[] = [];
  // A done Task shows no due date at all: it is not overdue, and the overdue word next to a finished Task is wrong.
  const due =
    summary.dueDate && !isDoneTask(summary)
      ? relativeDue(summary.dueDate, now, locale)
      : undefined;
  if (due && due.text) {
    // A Project's date is its target (`target` and the date); a Task's is due, and an overdue one says so alone.
    if (summary.kind === "project") {
      parts.push({
        key: "due",
        text: `${labels.target}: ${workDate(summary.dueDate, now, locale, { inline: true })}`,
        tone: due.tone,
      });
    } else {
      parts.push({
        key: "due",
        text:
          due.tone === "overdue"
            ? due.text
            : [
                `${labels.due} ${workDate(summary.dueDate, now, locale, { inline: true })}`,
                dueClockText(summary.dueDate, locale),
              ]
                .filter(Boolean)
                .join(" "),
        tone: due.tone,
      });
    }
  }
  const datapoints = summary.datapoints;
  if (datapoints?.tasks !== undefined) {
    parts.push({
      key: "tasks",
      text: labels.tasksDoneOf(datapoints.tasks.done, datapoints.tasks.total),
    });
  }
  if (datapoints?.overdue !== undefined && datapoints.overdue > 0) {
    parts.push({
      key: "overdue",
      text: labels.overdueTasks(datapoints.overdue),
      tone: "overdue",
    });
  }
  if (datapoints?.contacts !== undefined) {
    parts.push({
      key: "contacts",
      text: `${labels.contacts}: ${datapoints.contacts}`,
    });
  }
  return parts.slice(0, 3);
}

/** Whether the status chip draws a glyph: a finished record (the check) or an unknown status (dashed), never an open one. */
function showsGlyph(
  labels: InlineSummaryLabels,
  summary: { kind: InlineSummaryKind; status: string },
): boolean {
  const known =
    summary.kind === "project" ? labels.projectStatus : labels.taskStatus;
  return (
    summary.status === "completed" ||
    !Object.prototype.hasOwnProperty.call(known, summary.status)
  );
}

/** A Task marked done ("completed"): it has no overdue state, so its due date is never shown as overdue. */
function isDoneTask(summary: { kind: string; status: string }): boolean {
  return summary.kind === "task" && summary.status === "completed";
}

/** Translated kind; the summary is for a Task or a Project only. */
function kindLabel(
  labels: InlineSummaryLabels,
  kind: InlineSummaryKind,
): string {
  return labels.kind[kind];
}

/** The Task's priority as "Priority: High"; only "high" and "urgent" get one, so normal and low add no part. */
function priorityText(
  labels: InlineSummaryLabels,
  priority: string | null | undefined,
): string | undefined {
  if (priority !== "high" && priority !== "urgent") return undefined;
  return `${labels.priorityLabel}: ${labels.priority[priority]}`;
}
