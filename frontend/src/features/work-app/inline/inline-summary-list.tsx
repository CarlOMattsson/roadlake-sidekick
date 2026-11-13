import { Fragment, type ReactNode } from "react";
import type { DueTone } from "../../mcp-apps/ui/due";
import { CardFoot } from "../../mcp-apps/ui/card";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
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
 * The card's one link row (§7: "Öppna …" and "+N fler" became one): "Öppna Agenda · 3 fler ›"
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
 * The shell of the list summaries: a title, one line of counts (or `empty` in their place), a few
 * plain-text rows and "Open", which asks the host for fullscreen. No inner scroll and no menus; the
 * full view is only shown in fullscreen. The rows never carry buttons.
 */
export function ListSummary({
  labels,
  kindLabel,
  lines,
  empty,
  onOpen,
  openLabel,
  kicker,
  className,
  children,
  aside,
}: {
  labels: InlineSummaryLabels;
  kindLabel: string;
  /** What the rows leave out ("+3 fler försenade"), on the line of "Open" at its end. */
  aside?: string;
  /** The kicker in full ("Arbete · 2 försenade · 1 idag · 3 kommande"); without it the app name alone. */
  kicker?: string;
  /** An extra class on the card, e.g. the agenda's own layout. */
  className?: string;
  lines: CountLine[];
  /** Shown instead of the counts when there is nothing to count. */
  empty?: string;
  /** Without it there is no Open button, e.g. when the agenda has nothing to open. */
  onOpen?: () => void;
  /** The words of the Open button ("Visa alla (25)"); without it the button says "Open". */
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
    </section>
  );
}

/** One part of an inline row's meta line, in its tone ("overdue" is red). */
export type InlineMetaPart = { text: string; tone?: DueTone };

/**
 * The row of every inline list card (the agenda and the board, designsystem §3 inline card): a button
 * the width of the card, at least 44 high, that opens its record or the room. The title takes the full width on its
 * own line, cut with an ellipsis, and the meta line stands under it, always ("11 dagar försenad · Pågår"). No ring and
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
 * An inline row's meta: the time and the status on one line, "9 dagar försenad · Pågår", from the builder of
 * the fullscreen rows (`rowStatus`, `rowDue`), so the agenda and the board say the same of the same Task. No Project: the card is short.
 */
export function inlineMeta(
  item: WorkItemRecord,
  now: Date,
  locale: string,
  word: (status: string) => string,
): InlineMetaPart[] {
  const due = rowDue(item, now, locale);
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
