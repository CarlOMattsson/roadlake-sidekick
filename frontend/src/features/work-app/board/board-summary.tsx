import { useEffect } from "react";
import {
  CountsBar,
  type CountsSegment,
  type CountsTone,
} from "../../mcp-apps/ui/counts-bar";
import { Card } from "../../mcp-apps/ui/card";
import { workDate } from "../../mcp-apps/ui/due";
import { OpenLink } from "../../mcp-apps/ui/open-link";
import { rowDue } from "../shared/record-meta";
import { InlineEmpty, InlineRow, inlineMeta } from "../inline/inline-summary";
import {
  InlineRefreshButton,
  RefreshFailure,
  refreshedOr,
  type ListRefresh,
} from "../inline/inline-refresh";
import "../inline/inline-summary.css";
import { workStatusLabel, type WorkLabels } from "../shared/labels";
import { boardLabelsFor } from "./board-labels";
import { unshownIn } from "./board-columns";
import {
  cardKey,
  boardColumns,
  hiddenRows,
  shownOrder,
} from "../shared/work-items";
import {
  TASK_STATUSES,
  isTaskStatus,
  type WorkBoardPage,
  type WorkItemRecord,
} from "../transport/transport";

/** Key of the Projects row. Projects sit in project-status columns, so they are counted apart. */
const PROJECT_ROW = "project";
/** How many nearest due Tasks the inline summary lists. */
const NEAREST_DUE = 3;
/** Colour support for the counts bar, one per open status (Klar is not in the bar); the legend carries the meaning. */
const TONE: Record<string, CountsTone> = {
  todo: "neutral",
  in_progress: "info",
  blocked: "warning",
};

export type SummaryRow = { key: string; label: string; count: number };

/**
 * One row per Task status column, then one Projects row when the board holds any Project. With the
 * server's totals (`column_totals`) a Task status row counts the whole board and the Projects row adds
 * the Projects the page does not hold; without them (an older server) every record on the page is counted
 * once. A column that holds only Projects (such as "active") gets no row of its own.
 */
export function summaryRows(page: WorkBoardPage, t: WorkLabels): SummaryRow[] {
  const taskCounts = new Map<string, number>();
  let projects = 0;
  for (const [column, list] of Object.entries(page.columns))
    for (const item of list) {
      if (item.kind === "project") projects += 1;
      else taskCounts.set(column, (taskCounts.get(column) ?? 0) + 1);
    }
  projects += unshownIn(page, PROJECT_ROW);
  const rows: SummaryRow[] = [];
  for (const key of boardColumns(page.columns)) {
    const total = isTaskStatus(key) ? page.column_totals?.[key] : undefined;
    const count = total ?? taskCounts.get(key) ?? 0;
    if (count === 0 && !(TASK_STATUSES as readonly string[]).includes(key))
      continue;
    rows.push({ key, label: workStatusLabel(t, key), count });
  }
  if (projects > 0)
    rows.push({ key: PROJECT_ROW, label: t.projects, count: projects });
  return rows;
}

/** What the text to the model says besides the status counts. */
export type SummaryTail = {
  /** The counts are only the page's and it has a next cursor: the text ends with "more not shown". */
  more: boolean;
  /** Open Tasks that are overdue on the whole board; 0 or missing says nothing. */
  overdue?: number;
};

/**
 * The text sent to the host model: counts and column names only, never record titles, so
 * "Status: 35 to do, 2 in progress, 1 blocked, 9 done; 7 overdue". Only Tasks are counted there;
 * Projects follow apart ("; projects: 2"). The numbers are the card's own. When the counts are only the
 * page's and it has a next cursor, the text ends with "more not shown" (the `more` label).
 */
export function summaryText(
  rows: SummaryRow[],
  t: WorkLabels,
  tail: SummaryTail,
): string {
  const b = boardLabelsFor(t.dateLocale);
  const parts = rows
    .filter((row) => row.key !== PROJECT_ROW)
    .map((row) => `${row.count} ${row.label.toLocaleLowerCase(t.dateLocale)}`);
  const projects = rows.find((row) => row.key === PROJECT_ROW);
  const overduePart = tail.overdue ? `; ${b.overdueCount(tail.overdue)}` : "";
  const projectPart = projects
    ? `; ${projects.label.toLocaleLowerCase(t.dateLocale)}: ${projects.count}`
    : "";
  if (tail.more) parts.push(b.more.toLocaleLowerCase(t.dateLocale));
  return `${t.board}: ${parts.join(", ")}${overduePart}${projectPart}`;
}

/**
 * Inline board view: counts per status, the nearest due Tasks, and one action that asks the host
 * for fullscreen. The full board is shown only in fullscreen, so drag and scroll never happen
 * inline. A board with no record at all is the room's empty state and its link, with no counts.
 */
export function BoardSummary({
  page,
  labels: t,
  onOpen,
  onOpenItem,
  onModelContext,
  refresh,
}: {
  page: WorkBoardPage;
  labels: WorkLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
  /** Opens one record from its row, in fullscreen; without it a row opens the board. */
  onOpenItem?: (item: WorkItemRecord) => void;
  /** Reads the board again from the card's corner; the room passes it only when the host answers the read. */
  refresh?: ListRefresh;
  /** Sends the counts to the host model once per shown summary; a no-op without host support. */
  onModelContext?: (summary: string) => void;
}) {
  const b = boardLabelsFor(t.dateLocale);
  const rows = summaryRows(page, t);
  const more = Boolean(page.next_cursor);
  // With the server's totals the card counts the whole board; only the rows it does not list are left out.
  const exact = Boolean(page.column_totals) && page.overdue_total !== undefined;
  // Read on every render, as the fullscreen board does, so the due days match the agenda card
  // after midnight (a frozen clock from mount made the board count one day less).
  const now = new Date();
  // Projects get a line of their own below the bar.
  const projectRow = rows.find((row) => row.key === PROJECT_ROW);
  // The open rows: `todo`, `in_progress` and `blocked`, as the Status list counts them; `completed` is not in the bar.
  // The page's open records feed the nearest-due list; the counts come from the rows (the server's totals).
  const segments: CountsSegment[] = [];
  const open: WorkItemRecord[] = [];
  for (const row of rows)
    if (TONE[row.key]) {
      segments.push({ ...row, tone: TONE[row.key]! });
      open.push(
        ...(page.columns[row.key] ?? []).filter((i) => i.kind !== "project"),
      );
    }
  // The open Tasks with a due date, nearest first (the Status list's date order), at most three.
  const nearest = shownOrder(
    page,
    "",
    open.filter((item) => item.kind === "task" && item.due_at),
  ).slice(0, NEAREST_DUE);
  const openCount = segments.reduce((sum, segment) => sum + segment.count, 0);
  const overdue =
    page.overdue_total ??
    open.filter((item) => rowDue(item, now, t.dateLocale)?.tone === "overdue")
      .length;
  // Every open row of the Status list the foot opens, minus the card's rows (one count with the agenda card).
  const hiddenCount = hiddenRows(openCount, nearest.length);
  const text = summaryText(rows, t, {
    more: more && !exact,
    overdue: exact ? overdue : 0,
  });
  useEffect(() => {
    onModelContext?.(text);
  }, [text, onModelContext]);
  // No record on any column and no further page: the room's empty state, with no counts.
  const blank =
    !more && Object.values(page.columns).every((list) => list.length === 0);
  return (
    // The card is named as the view it opens (`status`). The kicker says the room, the view and the date, and the title
    // is the statement with the overdue and open counts (`headline`).
    <Card
      aria-label={t.status}
      className="work-compact-card work-compact-board"
      eyebrow={`${t.title} · ${t.status} · ${refreshedOr(refresh, t.dateLocale, workDate(now.toISOString(), now, t.dateLocale, { inline: true, relative: false }))}`}
      title={blank ? undefined : b.headline(overdue, openCount, more && !exact)}
    >
      {refresh ? (
        <>
          <InlineRefreshButton refresh={refresh} dateLocale={t.dateLocale} />
          <RefreshFailure refresh={refresh} dateLocale={t.dateLocale} />
        </>
      ) : null}
      {blank ? (
        <InlineEmpty
          locale={t.dateLocale}
          text={{
            title: b.empty,
            hint: b.emptyHint,
            example: t.workEmptyAsk,
          }}
          onOpen={onOpen}
          openLabel={b.openBoard}
        />
      ) : (
        <>
          <CountsBar label={t.status} segments={segments} />
          {projectRow ? (
            <p className="work-compact-status">{`${projectRow.label}: ${projectRow.count}`}</p>
          ) : null}
          {nearest.length > 0 ? (
            // What the rows are, as a meta label over them: `nearestOverdue` when all three are
            // late, else `nearest`.
            <p className="work-compact-group">
              {nearest.every(
                (item) => rowDue(item, now, t.dateLocale)?.tone === "overdue",
              )
                ? b.nearestOverdue
                : b.nearest}
            </p>
          ) : null}
          {nearest.length > 0 ? (
            // The rows of the agenda card (01), with the status before the due words: the status, then how late it is.
            <ul className="work-compact-rows">
              {nearest.map((item) => (
                <InlineRow
                  key={cardKey(item)}
                  title={item.title}
                  meta={inlineMeta(item, now, t.dateLocale, (s) =>
                    workStatusLabel(t, s),
                  )}
                  onOpen={() => (onOpenItem ? onOpenItem(item) : onOpen())}
                />
              ))}
            </ul>
          ) : null}
          {/* The card's one main link, as on the agenda card. What the list leaves out is counted in it ("22+ more"
          while pages remain), not said by the title. */}
          <OpenLink
            label={b.openBoard}
            {...(hiddenCount > 0
              ? {
                  more: b.hiddenCount.replace(
                    "{count}",
                    `${hiddenCount}${more && !exact ? "+" : ""}`,
                  ),
                }
              : {})}
            onOpen={onOpen}
          />
        </>
      )}
    </Card>
  );
}
