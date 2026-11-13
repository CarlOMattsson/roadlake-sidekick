import type { CSSProperties } from "react";
import { workStatusLabel } from "../../shared/labels";
import { StatusGlyph } from "../../../mcp-apps/ui/status-glyph";
import { UndoMeta, fillLabel } from "../agenda-undo";
import {
  RowMenuButton,
  rowMenuHandlers,
  rowMenuHint,
} from "../../shared/row-menu";
import { cardKey, type AgendaBucket } from "../../shared/work-items";
import { domainAccentOf, type WorkItemRecord } from "../../transport/transport";
import { RecordTitle } from "../../board/board-card";
import { RecordMeta } from "../../shared/record-meta";
import { OpenChevron } from "../../tasks/task-detail-controls";
import { recurringDoneText, selectedRow, triagedNote } from "./agenda-helpers";
import { AgendaNotice, rowSpot } from "./agenda-notice";
import { RowMenuPanel } from "./row-menu-panel";
import type { AgendaRowContext } from "./row-context";

/** The ring (or glyph) that leads a row: a button that ticks a Task done or opens it again, else the status glyph alone. */
function RowGlyph({
  ctx,
  record,
  item,
}: {
  ctx: AgendaRowContext;
  record: WorkItemRecord;
  item: WorkItemRecord;
}) {
  const { labels: t, disabled, offers, writes } = ctx;
  const statusText = workStatusLabel(t, item.status);
  const ring =
    item.status === "completed"
      ? offers.statusOffered("todo", item.status)
      : offers.statusOffered("completed", item.status);
  if (item.kind === "task" && ring)
    return (
      <button
        type="button"
        className="work-agenda-glyph"
        aria-label={fillLabel(
          item.status === "completed" ? t.agendaReopen : t.agendaComplete,
          { title: item.title },
        )}
        disabled={disabled}
        onClick={() => writes.toggleDone(record)}
      >
        <StatusGlyph kind="task" status={item.status} label={statusText} />
      </button>
    );
  if (item.kind === "project")
    return (
      <span className="work-agenda-glyph">
        <StatusGlyph kind="project" status={item.status} label={statusText} />
      </span>
    );
  // The host cannot write this change (a done Task cannot be opened again): the glyph is shown, not pressed.
  if (item.kind === "task")
    return (
      <span className="work-agenda-glyph">
        <StatusGlyph kind="task" status={item.status} label={statusText} />
      </span>
    );
  // A Step or an action: a small muted square, shown and not pressed, so every title starts in one column and a Step
  // never stands left of the Task it belongs to. It says only done or not done: an action's own statuses are
  // not the ring's to tell, so none of them draws the dashed "unknown" frame.
  const done = item.status === "completed" || item.status === "done";
  return (
    <span className="work-agenda-glyph work-agenda-glyph-sub">
      <StatusGlyph
        kind="step"
        status={done ? "completed" : "todo"}
        label={statusText}
      />
    </span>
  );
}

/** The inline style of a row: the height its fold starts from while it leaves, and the outline of a selected row. */
function rowStyle(
  leaveHeight: number | undefined,
  isSelected: boolean,
): CSSProperties | undefined {
  if (leaveHeight !== undefined)
    return {
      "--leave-h": `${leaveHeight}px`,
      ...(isSelected ? selectedRow : {}),
    } as CSSProperties;
  return isSelected ? selectedRow : undefined;
}

/**
 * One record of the agenda: its ring, title and meta line (or its Undo, "Moving…" or the waiting mark in the meta line's
 * place), the quick choices when they are open, and the hidden menu button for screen readers.
 */
export function AgendaRow({
  ctx,
  record,
  group,
}: {
  ctx: AgendaRowContext;
  record: WorkItemRecord;
  group: AgendaBucket;
}) {
  const {
    labels: t,
    now,
    disabled,
    rows,
    rowQueue,
    menu,
    offers,
    writes,
  } = ctx;
  const drawn = rows.current(record);
  // A tick that waits in the phone's outbox (the widget's too) is drawn done, with "Skickas…" for its meta line.
  const sending =
    drawn.kind === "task" && ctx.sending.has(drawn.id.toLowerCase());
  const item = sending ? { ...drawn, status: "completed" } : drawn;
  // A Step whose Task is done here (ticked, waiting to be sent, or read so) says so instead of its date.
  const parentDone =
    item.kind !== "task" &&
    item.kind !== "project" &&
    typeof item.task_id === "string" &&
    ctx.doneTasks.has(item.task_id.toLowerCase());
  const key = cardKey(item);
  const isSelected = ctx.selected === key;
  const accent = domainAccentOf(item.domain_accent);
  const moved = rows.triaged[key] === true;
  // A recurring Task marked done here: the server reopened it for its next date (see isRecurringCycle).
  const cycle = rows.cycleOf(key);
  const cycleText = cycle ? recurringDoneText(t, item.due_at, now) : undefined;
  const note = moved ? (cycleText ?? triagedNote(t, item, now)) : undefined;
  const entry = rows.undos[key];
  /** What the row's last change did, in its Undo line. */
  function undoText(): string {
    if (cycleText && entry) return cycleText;
    if (entry?.due) return fillLabel(t.movedTo, { status: entry.due.label });
    if (entry?.to === "completed")
      return ctx.boardAvailable
        ? t.agendaDoneInStatus
        : workStatusLabel(t, "completed");
    return workStatusLabel(t, entry?.to ?? "");
  }
  /** The row's Ångra, where the host can write the change back. A cycle's Ångra puts the due date it had back. */
  function undoAction(): (() => void) | undefined {
    if (!entry) return undefined;
    if (cycle)
      return offers.offers("update_task", { changes: { due_at: null } })
        ? () =>
            writes.undoWrite(
              { ...entry, due: { from: cycle.from, label: "" } },
              item.title,
            )
        : undefined;
    const offered = offers.offers("update_task", {
      changes: entry.due ? { due_at: null } : { status: entry.from },
      ...(entry.due ? {} : { from_status: entry.to }),
    });
    return offered ? () => writes.undoWrite(entry, item.title) : undefined;
  }
  const writing = rowQueue.pending(key) > 0;
  const queued = rowQueue.queued(key);
  const choices = offers.rowHasChoices(item);
  const open = choices && menu.menu === key;
  const setOpen = (next: boolean) => menu.setOpen(key, next);
  const rowClass = [
    "work-agenda-row",
    accent ? "work-accent" : "",
    moved ? "work-agenda-row-moved" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <li
      className={rowClass}
      data-agenda-key={key}
      data-accent={accent ?? undefined}
      tabIndex={-1}
      aria-current={isSelected || undefined}
      aria-busy={writing || undefined}
      data-leaving={rows.leaving[key] !== undefined || undefined}
      // While Ångra shows (not while a tap waits): the ring is filled, the title in text-2 and › hidden by CSS.
      data-undo={entry && !queued ? "on" : undefined}
      data-muted={parentDone || undefined}
      style={rowStyle(rows.leaving[key], isSelected)}
      {...(choices ? rowMenuHandlers(open, setOpen) : {})}
    >
      <div className="work-agenda-line">
        {sending ? (
          <span className="work-agenda-glyph">
            <StatusGlyph
              kind="task"
              status="completed"
              label={workStatusLabel(t, "completed")}
            />
          </span>
        ) : (
          <RowGlyph ctx={ctx} record={record} item={item} />
        )}
        <div className="work-agenda-body">
          <RecordTitle
            item={item}
            disabled={disabled}
            onOpen={ctx.onOpen}
            hint={choices ? rowMenuHint(t) : undefined}
          />
          {sending ? (
            <p className="work-card-meta">
              <span className="sk-queued">{t.sending}</span>
            </p>
          ) : queued ? (
            // A tap that waits behind the row's running write: shown at once, in the meta line's place.
            <p className="work-card-meta">
              <span className="sk-queued">{t.queued}</span>
            </p>
          ) : entry || writing ? (
            <UndoMeta
              text={undoText()}
              moving={!entry}
              labels={t}
              disabled={disabled}
              onUndo={undoAction()}
              onExpire={() => rows.expire(key)}
            />
          ) : (
            <>
              {parentDone ? (
                <p className="work-card-meta">{t.agendaParentDone}</p>
              ) : (
                <RecordMeta item={item} labels={t} now={now} group={group} />
              )}
              {note !== undefined && (
                <p className="work-agenda-moved">{note}</p>
              )}
            </>
          )}
        </div>
        {/* Every row that opens a view ends in › (§3, Chevronregeln); Ångra takes its place. */}
        {!(entry || writing) && <OpenChevron />}
      </div>
      {/* A failed write of this row says so here, with its Try again, and not at the top of the list. */}
      <AgendaNotice spot={rowSpot(key)} source={ctx.notice} labels={t} />
      {choices && open && (
        <RowMenuPanel
          ctx={ctx}
          record={record}
          item={item}
          group={group}
          moved={moved}
          onClose={() => setOpen(false)}
        />
      )}
      {choices && (
        <RowMenuButton
          label={t.rowMenuButton(item.title)}
          open={() => setOpen(true)}
          firstChoice=".work-agenda-menu .sk-chip"
        />
      )}
    </li>
  );
}
