import { Fragment } from "react";
import {
  type DueLocale,
  type DueTone,
  relativeDue,
  workDate,
} from "../mcp-apps/ui/due";
import { Progress } from "../mcp-apps/ui/progress";
import "./inline-summary.css";
import { StatusGlyph } from "../mcp-apps/ui/status-glyph";
import { CardFoot } from "../mcp-apps/ui/card";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import { ErrorNotice } from "../mcp-apps/ui/states";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import {
  ListSummary,
  statusLabel,
  type InlineSummaryKind,
  type InlineSummaryNotice,
} from "./inline-summary-list";

// The public surface of the inline cards stays here; the agenda, hierarchy and shared list parts live in siblings.
export { AgendaSummary, type InlineAgendaWrite } from "./inline-agenda-summary";
export { HierarchySummary } from "./inline-hierarchy-summary";
export {
  InlineRow,
  OpenFoot,
  inlineMeta,
  type InlineMetaPart,
  type InlineSummaryKind,
  type InlineSummaryNotice,
} from "./inline-summary-list";

/** At most this many Contact names are listed inline. */
const CONTACT_ROWS = 3;

/**
 * The datapoints the summary may show. Each is optional. `steps` is drawn as a progress count
 * (done/total with a thin bar); `contacts` and `subtasks` are counts in the meta line. For a Task,
 * `steps` counts its Steps; for a Project, `subtasks` counts its Tasks.
 */
export type InlineSummaryDatapoints = {
  steps?: { done: number; total: number };
  contacts?: number;
  subtasks?: number;
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
  /** A Task's priority; only "high" and "urgent" are shown, as words. */
  priority?: string | null;
  /** A Task's description: one line, cut with an ellipsis. Absent or empty means no line. */
  description?: string | null;
  /** The name of the Task's Project, when the record carries it. */
  projectTitle?: string | null;
};

/**
 * The inline summary. Loading, empty and error come in through `state`; the ready state takes the
 * record and its actions: "Done" (a Task only, given by `onComplete`, the primary action; `busy`
 * disables it while the write runs) and "Open" (asks the host for fullscreen; the secondary action
 * beside Done, or the only one). A `notice` shows a write's conflict or failure. The summary has no
 * inner scroll and no menus.
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
      onRetry?: () => void;
    }
  | {
      state: "ready";
      labels: InlineSummaryLabels;
      summary: InlineSummaryData;
      onOpen?: () => void;
      onComplete?: () => void;
      busy?: boolean;
      notice?: InlineSummaryNotice;
    };

/** One line of a Task's description: whitespace collapsed, cut at `max` characters with an ellipsis. */
export function oneLine(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

export function InlineSummary(props: InlineSummaryProps) {
  const { labels } = props;

  if (props.state === "loading") {
    return (
      <section className="work-compact-card sk-card" aria-busy="true">
        <p role="status" className="work-compact-status">
          {labels.loading}
        </p>
        <span className="work-compact-skeleton" aria-hidden="true" />
        <span
          className="work-compact-skeleton work-compact-skeleton-short"
          aria-hidden="true"
        />
      </section>
    );
  }

  if (props.state === "empty") {
    return (
      <section className="work-compact-card sk-card">
        <p className="work-compact-status">{labels.empty}</p>
      </section>
    );
  }

  if (props.state === "gone") {
    return (
      <section className="work-compact-card sk-card">
        <p className="sk-eyebrow">{props.kindLabel}</p>
        <p role="status" className="work-compact-status">
          {labels[props.goneKey]}
        </p>
      </section>
    );
  }

  if (props.state === "error") {
    return (
      <section className="work-compact-card sk-card">
        <p className="sk-eyebrow">{props.kindLabel}</p>
        <ErrorNotice locale={labels.dateLocale} onRetry={props.onRetry} />
      </section>
    );
  }

  const { summary, onOpen, onComplete, busy, notice } = props;
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
  // Done is the primary action of a Task that can be marked done. Open is navigation, so it is the
  // family's open text button with › (designsystem §3), beside Done or alone.
  const openText =
    summary.kind === "project"
      ? labels.showProject
      : onComplete
        ? labels.showMore
        : labels.showTask;

  return (
    <section
      className="work-compact-card sk-card"
      aria-label={kindLabel(labels, summary.kind)}
    >
      <p className="work-compact-kind sk-eyebrow">
        {kindLabel(labels, summary.kind)}
      </p>
      <p className="work-compact-title sk-card__title">{summary.title}</p>
      <p>
        <span className="work-chip">
          <StatusGlyph kind={summary.kind} status={summary.status} />
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
      {onComplete || onOpen ? (
        <CardFoot>
          <div className="work-compact-actions">
            {onComplete ? (
              <button
                type="button"
                className="work-compact-action sk-btn--primary"
                onClick={onComplete}
                disabled={busy}
                aria-busy={busy || undefined}
              >
                {busy ? labels.completing : labels.complete}
              </button>
            ) : null}
            {onOpen ? (
              <button
                type="button"
                className="work-compact-action sk-btn--open"
                onClick={onOpen}
              >
                {openText}
                <ChevronRightIcon />
              </button>
            ) : null}
          </div>
        </CardFoot>
      ) : null}
      {notice ? <NoticeBlock notice={notice} /> : null}
    </section>
  );
}

/** A message under a summary with an optional action (read again or retry), as the Task summary shows it. */
function NoticeBlock({ notice }: { notice: InlineSummaryNotice }) {
  return (
    <div role="alert" className="work-compact-notice sk-error sk-error--card">
      <p>{notice.message}</p>
      {notice.action ? (
        <button
          type="button"
          className="work-compact-action"
          onClick={notice.action}
        >
          {notice.actionLabel}
        </button>
      ) : null}
    </div>
  );
}

/** A matching Contact as the inline list shows it: its id keys the row, its name is the text. */
export type ContactName = { id: string; name: string };

/**
 * Inline Contact list: how many Contacts match, counted on the page read so far, then the first
 * three names. `more` marks a page with a next cursor, so the count is shown with "+". A name equal
 * to `query` (ignoring case and surrounding spaces) is listed first; the rest keep the order read.
 */
export function ContactsSummary({
  count,
  more,
  contacts = [],
  query = "",
  labels,
  onOpen,
}: {
  count: number;
  more: boolean;
  contacts?: ContactName[];
  query?: string;
  labels: InlineSummaryLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
}) {
  const wanted = query.trim().toLocaleLowerCase();
  const isExact = (contact: ContactName) =>
    wanted !== "" && contact.name.trim().toLocaleLowerCase() === wanted;
  // Array.prototype.sort is stable, so only the exact matches move, to the front.
  const shown = [...contacts]
    .sort((a, b) => Number(isExact(b)) - Number(isExact(a)))
    .slice(0, CONTACT_ROWS);
  return (
    <ListSummary
      labels={labels}
      kindLabel={labels.kind.contacts}
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
      onOpen={onOpen}
      openLabel={labels.showAll(count, more)}
    >
      {shown.length > 0 ? (
        <ul className="work-compact-rows">
          {shown.map((contact) => (
            <li key={contact.id} className="work-compact-row">
              <span className="work-compact-row-title">{contact.name}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </ListSummary>
  );
}

/** How many Projects and Tasks a Contact is linked to, counted on its context read; `more` marks a partial read. */
export type ContactLinkCounts = {
  projects: number;
  projectsMore: boolean;
  tasks: number;
  tasksMore: boolean;
};

/**
 * The inline Contact card: the kind label, the name, the relationship as a small chip (when set), one
 * meta line with "role · organization" (or the e-mail when neither is set) and the counts of its
 * Projects and Tasks (a count is shown only when there is one), and "Open", which asks the host for
 * fullscreen. The address is never shown inline. The card has no fields and no Edit: the Contact view
 * with its editor is shown in fullscreen only. `counts` is absent while the read runs or when it
 * failed; the card then shows what it has.
 */
export function ContactSummary({
  kindLabel,
  name,
  email,
  relationship,
  organization,
  role,
  counts,
  labels,
  onOpen,
}: {
  kindLabel: string;
  name: string;
  email: string | null;
  relationship?: string | null;
  organization?: string | null;
  role?: string | null;
  counts?: ContactLinkCounts;
  labels: InlineSummaryLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
}) {
  const meta: string[] = [];
  const roleAndOrganization = [role, organization].filter(Boolean).join(" · ");
  if (roleAndOrganization) meta.push(roleAndOrganization);
  else if (email) meta.push(email);
  if (counts && (counts.projects > 0 || counts.projectsMore))
    meta.push(
      `${labels.projectCount}: ${counts.projects}${counts.projectsMore ? "+" : ""}`,
    );
  if (counts && (counts.tasks > 0 || counts.tasksMore))
    meta.push(
      `${labels.taskCount}: ${counts.tasks}${counts.tasksMore ? "+" : ""}`,
    );
  return (
    <section
      className="work-compact-card sk-card work-compact-contact"
      aria-label={kindLabel}
    >
      <div className="work-compact-contact-text">
        <p className="work-compact-kind sk-eyebrow">{kindLabel}</p>
        <p className="work-compact-title sk-card__title">{name}</p>
        {relationship ? (
          <p>
            <span className="work-chip">{relationship}</span>
          </p>
        ) : null}
        {meta.length > 0 ? (
          <p className="work-compact-status">{meta.join(" · ")}</p>
        ) : null}
      </div>
      <CardFoot>
        <button
          type="button"
          className="work-compact-action sk-btn--open"
          onClick={onOpen}
        >
          {labels.open}
          <ChevronRightIcon />
        </button>
      </CardFoot>
    </section>
  );
}

type MetaPart = { key: string; text: string; tone?: DueTone };

/**
 * The meta line: due, then contacts and subtasks, joined by " · " in that order. A relative due
 * date comes from relativeDue (owner calendar day, given `now`); an overdue text already
 * says so, so it is shown alone and every other due text gets the "Due" label in front.
 */
function metaParts(
  summary: InlineSummaryData,
  labels: InlineSummaryLabels,
  locale: DueLocale,
  now: Date,
): MetaPart[] {
  const parts: MetaPart[] = [];
  // A done Task shows no due date at all: it is not overdue, and "Försenad" next to a finished Task is wrong.
  const due =
    summary.dueDate && !isDoneTask(summary)
      ? relativeDue(summary.dueDate, now, locale)
      : undefined;
  if (due && due.text) {
    // A Project's date is its target ("Mål: tis 15 dec"); a Task's is due, and an overdue one says so alone.
    if (summary.kind === "project") {
      parts.push({
        key: "due",
        text: `${labels.target}: ${due.text}`,
        tone: due.tone,
      });
    } else {
      parts.push({
        key: "due",
        text:
          due.tone === "overdue"
            ? `${labels.overdueSince} ${workDate(summary.dueDate, now, locale, { inline: true, relative: false })}`
            : `${labels.due} ${workDate(summary.dueDate, now, locale, { inline: true })}`,
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
  if (datapoints?.subtasks !== undefined) {
    parts.push({
      key: "subtasks",
      text: `${labels.subtasks}: ${datapoints.subtasks}`,
    });
  }
  return parts.slice(0, 3);
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

/** The word for a Task's priority; only "high" and "urgent" get one, so normal and low add no part. */
function priorityText(
  labels: InlineSummaryLabels,
  priority: string | null | undefined,
): string | undefined {
  if (priority !== "high" && priority !== "urgent") return undefined;
  return labels.priority[priority];
}
