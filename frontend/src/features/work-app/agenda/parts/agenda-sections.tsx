import type { ReactNode } from "react";
import { Fold } from "../../../mcp-apps/ui/fold";
import { Counted } from "../../../mcp-apps/ui/count";
import type { WorkItemRecord } from "../../transport/transport";
import { RecordTitle } from "../../board/board-card";
import {
  cardKey,
  type AgendaBucket,
  type DatedAgendaSection,
} from "../../shared/work-items";
import {
  LONG_WAIT_DAYS,
  waitingRows,
  type WaitingLabels,
  type WaitingRow,
} from "../../shared/waiting";
import { sectionHeading, stickyHeading } from "./agenda-helpers";
import { AgendaNotice, rowSpot } from "./agenda-notice";
import { AgendaRow } from "./agenda-row";
import { MoveAllOverdue } from "./move-all-overdue";
import type { AgendaRowContext } from "./row-context";

/** The group heading that sticks under the host's navigation while its records scroll under it. */
function GroupHead({
  children,
  overdue = false,
  focusable = false,
}: {
  children: ReactNode;
  /** The Overdue group's heading carries `data-group="overdue"`. */
  overdue?: boolean;
  /** Focus can be sent to the heading (an emptied group hands it focus). */
  focusable?: boolean;
}) {
  return (
    <div className="work-agenda-group-head" style={stickyHeading}>
      <h3
        className="work-agenda-group"
        data-group={overdue ? "overdue" : undefined}
        tabIndex={focusable ? -1 : undefined}
      >
        {children}
      </h3>
    </div>
  );
}

/** One group of dated records: its heading, the rows still to deal with, the handled ones under a line, and the move-all action. */
export function AgendaSection({
  ctx,
  section,
  rows,
  moveAllOffered,
  onMoveAll,
}: {
  ctx: AgendaRowContext;
  section: DatedAgendaSection;
  /** The rows of the group as shown: those still open, and those handled (they sink under a line). */
  rows: { open: WorkItemRecord[]; handled: WorkItemRecord[] };
  /** The host can reschedule in bulk. */
  moveAllOffered: boolean;
  onMoveAll: (records: WorkItemRecord[]) => void;
}) {
  const { labels: t, now, disabled } = ctx;
  const overdue = section.group === "overdue";
  // The rows still to deal with: what "Flytta N till imorgon" moves and what the heading counts, one number at once
  // (a row standing for its Ångra is not counted, so "Försenade (4)" and "Flytta 4" agree). Only Tasks: the move takes
  // Tasks alone, and a Step is its Task's to deal with. A tick waiting to be sent counts as done.
  const movable = rows.open.filter(
    (item) =>
      item.kind === "task" &&
      ctx.rows.current(item).status !== "completed" &&
      !ctx.sending.has(item.id.toLowerCase()) &&
      !ctx.rows.triaged[cardKey(item)],
  ).length;
  const heading = sectionHeading(t, section, now, overdue ? movable : 0);
  return (
    <section aria-label={heading}>
      <GroupHead overdue={overdue} focusable>
        <Counted text={heading} />
      </GroupHead>
      {rows.open.length > 0 && (
        <ul className="work-list">
          {rows.open.map((record) => (
            <AgendaRow
              key={cardKey(record)}
              ctx={ctx}
              record={record}
              group={section.group}
            />
          ))}
        </ul>
      )}
      {rows.handled.length > 0 && (
        <ul className="work-list work-agenda-handled">
          {rows.handled.map((record) => (
            <AgendaRow
              key={cardKey(record)}
              ctx={ctx}
              record={record}
              group={section.group}
            />
          ))}
        </ul>
      )}
      {/* The group's action after its last row, so the heading meets its first row. */}
      {overdue && movable > 0 && moveAllOffered && (
        <MoveAllOverdue
          labels={t}
          count={movable}
          disabled={disabled}
          onMove={() => onMoveAll(section.items)}
        />
      )}
      {/* A failed "Flytta alla" or its Ångra says so under the button, with its Try again. */}
      {overdue && (
        <AgendaNotice spot="moveAll" source={ctx.notice} labels={t} />
      )}
    </section>
  );
}

/**
 * "Klar idag (n) ⌄" last in the Agenda, folded until opened. The same markup and classes as Status's "Klar (n) ⌄"
 * (board.tsx); a ring tap opens the Task again and the row goes back to its group.
 */
export function DoneTodaySection({
  ctx,
  done,
  open,
  onToggle,
}: {
  ctx: AgendaRowContext;
  done: { record: WorkItemRecord; group: AgendaBucket }[];
  open: boolean;
  onToggle: () => void;
}) {
  const { labels: t } = ctx;
  return (
    <section
      className="work-column"
      aria-label={t.agendaDoneToday}
      data-agenda-done=""
    >
      <h3>
        <Fold
          text={`${t.agendaDoneToday} (${done.length})`}
          meta={t.agendaDoneSince}
          open={open}
          onToggle={onToggle}
        />
      </h3>
      {open && (
        <ul className="work-list">
          {done.map(({ record, group }) => (
            <AgendaRow
              key={cardKey(record)}
              ctx={ctx}
              record={record}
              group={group}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/** The waiting view: the Tasks waiting on someone, who, for how long, and the reminder button. */
export function WaitingSection({
  ctx,
  labels: wt,
  records,
  reminded,
  onRemind,
}: {
  ctx: AgendaRowContext;
  labels: WaitingLabels;
  records: WorkItemRecord[];
  reminded: Record<string, boolean>;
  onRemind: (record: WorkItemRecord) => void;
}) {
  return (
    <section aria-label={wt.heading(records.length)}>
      <GroupHead>{wt.heading(records.length)}</GroupHead>
      <ul className="work-list">
        {waitingRows(records, ctx.now).map((row) => (
          <WaitingRowView
            key={cardKey(row.item)}
            ctx={ctx}
            labels={wt}
            row={row}
            reminded={reminded[cardKey(row.item)] === true}
            onRemind={onRemind}
          />
        ))}
      </ul>
    </section>
  );
}

/** One row of the waiting view: who, for how long, the Task, and the reminder button. */
function WaitingRowView({
  ctx,
  labels: wt,
  row: { item, who, days },
  reminded: set,
  onRemind,
}: {
  ctx: AgendaRowContext;
  labels: WaitingLabels;
  row: WaitingRow;
  reminded: boolean;
  onRemind: (record: WorkItemRecord) => void;
}) {
  const { disabled, rowQueue, offers } = ctx;
  const key = cardKey(item);
  const long = days !== null && days >= LONG_WAIT_DAYS;
  return (
    <li
      className="work-agenda-row work-waiting-row"
      data-agenda-key={key}
      tabIndex={-1}
      aria-busy={rowQueue.pending(key) > 0 || undefined}
    >
      <p className="work-waiting-who">
        <span className="work-waiting-name">{who ?? wt.someone}</span>
        <span
          className="work-waiting-days"
          data-tone={long ? "overdue" : undefined}
        >
          {wt.days(days)}
        </span>
      </p>
      <div className="work-agenda-body">
        <RecordTitle item={item} disabled={disabled} onOpen={ctx.onOpen} />
      </div>
      <AgendaNotice
        spot={rowSpot(key)}
        source={ctx.notice}
        labels={ctx.labels}
      />
      {item.kind === "task" &&
        offers.offers("update_task", { changes: { follow_up_at: null } }) && (
          <div className="work-waiting-actions">
            <button
              type="button"
              className="work-waiting-remind"
              aria-label={wt.remindName(item.title)}
              disabled={disabled || set}
              onClick={() => onRemind(item)}
            >
              {wt.remind}
            </button>
            {set && (
              <p role="status" className="work-waiting-reminded">
                {wt.reminded}
              </p>
            )}
          </div>
        )}
    </li>
  );
}
