import { Fragment, useContext, type ReactNode } from "react";
import type { DueTone } from "../../mcp-apps/ui/due";
import { CardFoot } from "../../mcp-apps/ui/card";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { RoomMessageContext } from "../../mcp-apps/ui/room-context";
import { EmptyState } from "../../mcp-apps/ui/states";
import type { InlineSummaryLabels } from "./inline-summary-labels";
import { knownLabel } from "../shared/labels";
import type { WorkItemRecord } from "../transport/transport";
import { OpenChevron } from "../tasks/task-detail-controls";
import { rowDue, rowStatus } from "../shared/record-meta";

export type InlineSummaryKind = "task" | "project";

/** A message under the summary; an action, when present, runs the next step (read again or retry). */
export type InlineSummaryNotice = {
  message: string;
  actionLabel?: string;
  action?: () => void;
};

/**
 * The notice of a card as the family's write error row: the message on one line at the card's full width, and the
 * action (read again, retry) as its text button under it when the line is long.
 */
export function NoticeRow({
  notice,
  locale,
}: {
  notice: InlineSummaryNotice;
  locale: string;
}) {
  return (
    <ErrorNotice placement="row" locale={locale} message={notice.message}>
      {notice.action ? (
        <button
          type="button"
          className="sk-error-retry sk-error-retry--text"
          onClick={notice.action}
        >
          {notice.actionLabel}
        </button>
      ) : null}
    </ErrorNotice>
  );
}

/**
 * One count of a list summary. `more` is set when the read was partial (another page, or a tree
 * the server cut), so the count is shown with "+" and is not taken as the total.
 */
export type CountLine = {
  key: string;
  label: string;
  count: number;
  more: boolean;
  /** The words of the count, when they are not "label: count". */
  text?: string;
};

/**
 * The card's one link row (§7: the open label and the more count became one): `openAgenda` with the count of the rest and a ›
 *, a tertiary open button, the rest after the name in the meta type. Without `aside` the name alone.
 */
export function OpenFoot({
  aside,
  label,
  onOpen,
}: {
  aside?: string;
  label: string;
  onOpen: () => void;
}) {
  return (
    <CardFoot>
      <button
        type="button"
        className="work-compact-action sk-btn--open"
        onClick={onOpen}
      >
        <span className="work-compact-open-text">
          {label}
          {aside ? (
            <span className="work-compact-more">{` · ${aside}`}</span>
          ) : null}
        </span>
        <ChevronRightIcon />
      </button>
    </CardFoot>
  );
}

/**
 * What an inline card says when its room holds nothing: the room's sentence, an optional line on what the room is
 * for, and the example to say to Claude (absent when there is nothing to create, e.g. a search without a match).
 */
export type InlineEmptyText = {
  title: string;
  hint?: string;
  example?: string;
};

/**
 * The body of an empty inline card, the same in every room: the family's empty state, whose example is sent through
 * the host's message function where there is one (shown as text where not), then the room's open link. No counts.
 */
export function InlineEmpty({
  locale,
  text,
  onOpen,
  openLabel,
}: {
  locale: string;
  text: InlineEmptyText;
  onOpen?: () => void;
  openLabel: string;
}) {
  const send = useContext(RoomMessageContext);
  const { example } = text;
  return (
    <>
      <EmptyState
        title={text.title}
        hint={text.hint}
        ask={
          example
            ? {
                locale,
                example,
                onSend: send ? () => void send(example) : undefined,
              }
            : undefined
        }
      />
      {onOpen ? <OpenFoot label={openLabel} onOpen={onOpen} /> : null}
    </>
  );
}

/**
 * The shell of the list summaries: a title, one line of counts (or `empty` in their place), a few
 * plain-text rows and "Open", which asks the host for fullscreen. No inner scroll and no menus; the
 * full view is only shown in fullscreen. The rows never carry buttons.
 */
export function ListSummary({
  labels,
  kindLabel,
  lines,
  empty,
  blank,
  onOpen,
  openLabel,
  kicker,
  className,
  children,
  aside,
}: {
  labels: InlineSummaryLabels;
  kindLabel: string;
  /** What the rows leave out (the count of the rest), on the line of "Open" at its end. */
  aside?: string;
  /** The kicker in full (the app name, then the overdue, today and upcoming counts); without it the app name alone. */
  kicker?: string;
  /** An extra class on the card, e.g. the agenda's own layout. */
  className?: string;
  lines: CountLine[];
  /** Shown instead of the counts when there is nothing to count here but the view holds more. */
  empty?: string;
  /** The room holds nothing at all: the card is the empty state and its open link, with no counts and no rows. */
  blank?: InlineEmptyText;
  /** Without it there is no Open button, e.g. when the agenda has nothing to open. */
  onOpen?: () => void;
  /** The words of the Open button (`openAgenda`); without it the button says "Open". */
  openLabel?: string;
  /** Optional rows between the count line and "Open", e.g. the Projects of a hierarchy. */
  children?: ReactNode;
}) {
  return (
    <section
      className={
        className
          ? `work-compact-card sk-card ${className}`
          : "work-compact-card sk-card"
      }
      aria-label={kindLabel}
    >
      <p className="work-compact-kind sk-eyebrow">{kicker ?? labels.appName}</p>
      {blank ? (
        <InlineEmpty
          locale={labels.dateLocale}
          text={blank}
          onOpen={onOpen}
          openLabel={openLabel ?? labels.open}
        />
      ) : (
        <>
          {empty ? (
            <>
              <p className="work-compact-title sk-card__title">{kindLabel}</p>
              <p className="work-compact-status">{empty}</p>
            </>
          ) : lines.length === 0 ? null : (
            <p className="work-compact-title sk-card__title">
              {lines.map((line, index) => (
                <Fragment key={line.key}>
                  {index > 0 ? " · " : null}
                  <span>
                    {line.text ??
                      `${line.label}: ${line.count}${line.more ? "+" : ""}`}
                  </span>
                </Fragment>
              ))}
            </p>
          )}
          {children}
          {onOpen ? (
            <OpenFoot
              aside={aside}
              label={openLabel ?? labels.open}
              onOpen={onOpen}
            />
          ) : null}
        </>
      )}
    </section>
  );
}

/** One part of an inline row's meta line, in its tone ("overdue" is red). */
export type InlineMetaPart = { text: string; tone?: DueTone };

/**
 * The row of every inline list card (the agenda and the board, designsystem §3 inline card): a button
 * the width of the card, at least 44 high, that opens its record or the room. The title takes the full width on its
 * own line, cut with an ellipsis, and the meta line stands under it, always (how late it is, then the status). No ring and
 * no indent: an inline card does not write.
 */
export function InlineRow({
  title,
  meta,
  onOpen,
}: {
  title: string;
  meta: InlineMetaPart[];
  onOpen: () => void;
}) {
  const parts = meta.filter((part) => part.text);
  return (
    <li className="work-compact-row">
      <button
        type="button"
        className="work-compact-open"
        aria-label={[title, ...parts.map((part) => part.text)].join(", ")}
        onClick={onOpen}
      >
        <span className="work-compact-row-title">{title}</span>{" "}
        {/* The row opens: the fullscreen row's ›, before the meta so the grid puts it on the title's line. */}
        <OpenChevron />
        {parts.length > 0 ? (
          <span className="work-compact-row-meta">
            {parts.map((part, index) => (
              <Fragment key={index}>
                {/* A space between the title and the meta, and between the parts, so the visible words run on in the button's name (WCAG 2.5.3). */}
                {index > 0 ? " " : null}
                <span data-tone={part.tone}>{part.text}</span>
              </Fragment>
            ))}
          </span>
        ) : null}
      </button>
    </li>
  );
}

/**
 * An inline row's meta: the time and the status on one line, how late it is, then the status, from the builder of
 * the fullscreen rows (`rowStatus`, `rowDue`), so the agenda and the board say the same of the same Task. No Project: the card is short.
 * Under a group that says the day (`group` "today", the agenda card's `today`), the row does not say it again.
 */
export function inlineMeta(
  item: WorkItemRecord,
  now: Date,
  locale: string,
  word: (status: string) => string,
  group?: string,
): InlineMetaPart[] {
  const due = rowDue(item, now, locale, group);
  return [
    { text: due?.text ?? "", tone: due?.tone },
    { text: rowStatus(item, word) ?? "" },
  ];
}

/** Translated status, using the Project or Task set by kind; unknown values arrive as they are. */
export function statusLabel(
  labels: InlineSummaryLabels,
  kind: InlineSummaryKind,
  status: string,
): string {
  return knownLabel(
    kind === "project" ? labels.projectStatus : labels.taskStatus,
    status,
  );
}
