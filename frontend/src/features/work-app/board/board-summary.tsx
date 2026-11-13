import { useEffect } from "react";
import {
  CountsBar,
  type CountsSegment,
  type CountsTone,
} from "../../mcp-apps/ui/counts-bar";
import { workDate } from "../../mcp-apps/ui/due";
import { rowDue } from "../shared/record-meta";
import {
  InlineEmpty,
  InlineRow,
  OpenFoot,
  inlineMeta,
} from "../inline/inline-summary";
import "../inline/inline-summary.css";
import { workStatusLabel, type WorkLabels } from "../shared/labels";
import {
  cardKey,
  boardColumns,
  hiddenRows,
  shownOrder,
} from "../shared/work-items";
import {
  TASK_STATUSES,
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
 * One row per Task status column, then one Projects row when the page holds any Project. Every
 * record on the page is counted exactly once, so the rows add up to the records shown. A column
 * that holds only Projects (such as "active") gets no row of its own.
 */
export function summaryRows(page: WorkBoardPage, t: WorkLabels): SummaryRow[] {
  const taskCounts = new Map<string, number>();
  let projects = 0;
  for (const [column, list] of Object.entries(page.columns))
    for (const item of list) {
      if (item.kind === "project") projects += 1;
      else taskCounts.set(column, (taskCounts.get(column) ?? 0) + 1);
    }
  const rows: SummaryRow[] = [];
  for (const key of boardColumns(page.columns)) {
    const count = taskCounts.get(key) ?? 0;
    if (count === 0 && !(TASK_STATUSES as readonly string[]).includes(key))
      continue;
    rows.push({ key, label: workStatusLabel(t, key), count });
  }
  if (projects > 0)
    rows.push({ key: PROJECT_ROW, label: t.projects, count: projects });
  return rows;
}

/**
 * The text sent to the host model: counts and column names only, never record titles, so
 * "Board: 3 to do, 2 in progress, 0 blocked, 1 done". Only Tasks are counted there; Projects follow
 * apart ("; projects: 2"). When the page has a next cursor, the text ends with "more not shown"
 * (Swedish: "fler finns").
 */
export function summaryText(
  rows: SummaryRow[],
  t: WorkLabels,
  more: boolean,
): string {
  const parts = rows
    .filter((row) => row.key !== PROJECT_ROW)
    .map((row) => `${row.count} ${row.label.toLocaleLowerCase(t.dateLocale)}`);
  const projects = rows.find((row) => row.key === PROJECT_ROW);
  const projectPart = projects
    ? `; ${projects.label.toLocaleLowerCase(t.dateLocale)}: ${projects.count}`
    : "";
  if (more) parts.push(t.boardMore.toLocaleLowerCase(t.dateLocale));
  return `${t.board}: ${parts.join(", ")}${projectPart}`;
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
  onModelContext,
}: {
  page: WorkBoardPage;
  labels: WorkLabels;
  /** Asks the host for fullscreen; the caller passes it only when the host can show it. */
  onOpen: () => void;
  /** Sends the counts to the host model once per shown summary; a no-op without host support. */
  onModelContext?: (summary: string) => void;
}) {
  const rows = summaryRows(page, t);
  const more = Boolean(page.next_cursor);
  const text = summaryText(rows, t, more);
  // Read on every render, as the fullscreen board does, so the due days match the agenda card
  // after midnight (a frozen clock from mount made the board count one day less).
  const now = new Date();
  // Projects get a line of their own below the bar.
  const projectRow = rows.find((row) => row.key === PROJECT_ROW);
  // One set of open rows: "Att göra", "Pågår" and "Blockerad" as the Status list shows and counts them, Tasks and
  // Steps. The bar, the headline's open and overdue counts and "+N fler öppna" all count it; Klar is not in the bar.
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
  const overdue = open.filter(
    (item) => rowDue(item, now, t.dateLocale)?.tone === "overdue",
  ).length;
  // Every open row of the Status list the foot opens, minus the card's rows (one count with the agenda card).
  const hiddenCount = hiddenRows(open.length, nearest.length);
  useEffect(() => {
    onModelContext?.(text);
  }, [text, onModelContext]);
  // No record on any column and no further page: the room's empty state, with no counts.
  const blank =
    !more && Object.values(page.columns).every((list) => list.length === 0);
  return (
    // The card is named as the view it opens, "Status" ("Tavla" once opened "Status").
    <section
      aria-label={t.status}
      className="sk-card work-compact-card work-compact-board"
    >
      {/* The head of the agenda card (01), so the card says what its rows are: "Arbete · Status · ons 4 nov"
          and "5 försenade av 13 öppna". */}
      <h2 tabIndex={-1} className="work-compact-kind sk-eyebrow">
        {`${t.title} · ${t.status} · ${workDate(now.toISOString(), now, t.dateLocale, { inline: true, relative: false })}`}
      </h2>
      {blank ? (
        <InlineEmpty
          locale={t.dateLocale}
          text={{
            title: t.boardEmpty,
            hint: t.boardEmptyHint,
            example: t.workEmptyAsk,
          }}
          onOpen={onOpen}
          openLabel={t.openBoard}
        />
      ) : (
        <>
          <p className="work-compact-title sk-card__title">
            {t.boardHeadline(overdue, open.length, more)}
          </p>
          <CountsBar label={t.status} segments={segments} />
          {projectRow ? (
            <p className="work-compact-status">{`${projectRow.label}: ${projectRow.count}`}</p>
          ) : null}
          {nearest.length > 0 ? (
            // What the rows are, as a meta label over them: "Äldst försenade" when all three are
            // late, else "Närmast i tid".
            <p className="work-compact-group">
              {nearest.every(
                (item) => rowDue(item, now, t.dateLocale)?.tone === "overdue",
              )
                ? t.boardNearestOverdue
                : t.boardNearest}
            </p>
          ) : null}
          {nearest.length > 0 ? (
            // The rows of the agenda card (01), with the status before the due words: "Pågår · 11 dagar försenad".
            <ul className="work-compact-rows">
              {nearest.map((item) => (
                <InlineRow
                  key={cardKey(item)}
                  title={item.title}
                  meta={inlineMeta(item, now, t.dateLocale, (s) =>
                    workStatusLabel(t, s),
                  )}
                  onOpen={onOpen}
                />
              ))}
            </ul>
          ) : null}
          {/* "Öppna status ›", as "Öppna agendan ›" on the agenda card: an inline card has no ink button. What
          the list leaves out stands at the end of its line; with nothing hidden but more pages, "Fler finns". */}
          <OpenFoot
            aside={
              hiddenCount > 0
                ? t.boardHiddenCount.replace("{count}", String(hiddenCount))
                : more
                  ? t.boardMore
                  : undefined
            }
            label={t.openBoard}
            onOpen={onOpen}
          />
        </>
      )}
    </section>
  );
}
