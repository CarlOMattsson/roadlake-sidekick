import type { CSSProperties } from "react";
import { workStatusLabel } from "../../shared/labels";
import { StatusGlyph } from "../../../mcp-apps/ui/status-glyph";
import { agendaLabelsFor } from "../agenda-labels";
import { UndoMeta, fillLabel, type AgendaUndo } from "../agenda-undo";
import { rowReceipt } from "../../shared/use-undo-receipts";
import {
  RowMenuButton,
  rowMenuHandlers,
  rowMenuHint,
  type MenuPoint,
} from "../../shared/row-menu";
import {
  cardKey,
  recordOfItem,
  type AgendaBucket,
} from "../../shared/work-items";
import { useRecordRow } from "../../../mcp-apps/ui/split-layout";
import { domainAccentOf, type WorkItemRecord } from "../../transport/transport";
import { RecordTitle } from "../../board/board-card";
import { RecordMeta } from "../../shared/record-meta";
import { isStandIn } from "../../shared/use-queued-records";
import { WaitingLine } from "../../shared/waiting-line";
import { WaitingMeta } from "../../shared/waiting-meta";
import { OpenChevron } from "../../tasks/task-detail-controls";
import { recurringDoneText, triagedNote } from "./agenda-helpers";
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
        // A Task made offline cannot be ticked until it has been sent.
        disabled={
          disabled ||
          (ctx.waiting.has(item.id.toLowerCase()) && isStandIn(item.id))
        }
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

/** The inline style of a row: the height its fold starts from while it leaves. A selected row is drawn by the stylesheet
 * (aria-current: the selected tone; focus: the one ring), never by an inline outline. */
function rowStyle(leaveHeight: number | undefined): CSSProperties | undefined {
  return leaveHeight !== undefined
    ? ({ "--leave-h": `${leaveHeight}px` } as CSSProperties)
    : undefined;
}

/**
 * What a row's last change did and how it is taken back: `text` for the row's own state line ("Klar · finns i Status",
 * "Flyttad till imorgon", a recurring Task's "Klar · nästa: …"), `receipt` for the receipt bar ("Klar: {title}"), and
 * `action`, the Ångra, where the host can write the change back. A cycle's Ångra puts the due date it had back.
 */
export function rowUndo(
  ctx: AgendaRowContext,
  item: WorkItemRecord,
  entry: AgendaUndo,
): { text: string; receipt: string; action?: () => void } {
  const { labels: t, now, rows, offers, writes } = ctx;
  const a = agendaLabelsFor(t.dateLocale);
  const key = cardKey(item);
  const cycle = rows.cycleOf(key);
  const what = entry.due
    ? fillLabel(t.movedTo, { status: entry.due.label })
    : workStatusLabel(t, cycle ? "completed" : entry.to);
  const text = cycle
    ? recurringDoneText(t, item.due_at, now)
    : entry.due
      ? what
      : entry.to === "completed" && ctx.boardAvailable
        ? a.doneInStatus
        : what;
  let action: (() => void) | undefined;
  if (cycle) {
    if (offers.offers("update_task", { changes: { due_at: null } }))
      action = () =>
        writes.undoWrite(
          { ...entry, due: { from: cycle.from, label: "" } },
          item.title,
        );
  } else if (
    offers.offers("update_task", {
      changes: entry.due ? { due_at: null } : { status: entry.from },
      ...(entry.due ? {} : { from_status: entry.to }),
    })
  )
    action = () => writes.undoWrite(entry, item.title);
  return { text, receipt: rowReceipt(what, item.title), action };
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
  const { labels: t, now, disabled, rows, rowQueue, menu, offers } = ctx;
  const a = agendaLabelsFor(t.dateLocale);
  const drawn = rows.current(record);
  // A tick that waits in the phone's outbox (the widget's too) is drawn done, with `sending` for its meta line.
  const sending =
    drawn.kind === "task" && ctx.sending.has(drawn.id.toLowerCase());
  const item = sending ? { ...drawn, status: "completed" } : drawn;
  // A Task whose edit, or whose making, waits in the outbox says so in its meta line (a tick has precedence).
  const waiting =
    drawn.kind === "task" && ctx.waiting.has(drawn.id.toLowerCase());
  // A Step whose Task is done here (ticked, waiting to be sent, or read so) says so instead of its date.
  const parentDone =
    item.kind !== "task" &&
    item.kind !== "project" &&
    typeof item.task_id === "string" &&
    ctx.doneTasks.has(item.task_id.toLowerCase());
  const key = cardKey(item);
  const isSelected = ctx.selected === key;
  // Its record's key, so the focus comes back to this row when the detail beside the list closes.
  const { "data-sk-record": recordAttr } = useRecordRow(recordOfItem(item));
  const accent = domainAccentOf(item.domain_accent);
  const moved = rows.triaged[key] === true;
  // A recurring Task marked done here: the server reopened it for its next date (see isRecurringCycle).
  const cycle = rows.cycleOf(key);
  const cycleText = cycle ? recurringDoneText(t, item.due_at, now) : undefined;
  const note = moved ? (cycleText ?? triagedNote(t, item, now)) : undefined;
  const entry = rows.undos[key];
  const undo = entry ? rowUndo(ctx, item, entry) : undefined;
  const writing = rowQueue.pending(key) > 0;
  const queued = rowQueue.queued(key);
  const choices = offers.rowHasChoices(item);
  const open = choices && menu.menu === key;
  const setOpen = (next: boolean, at?: MenuPoint) =>
    menu.setOpen(key, next, at);
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
      data-sk-row=""
      data-agenda-key={key}
      data-sk-record={recordAttr}
      data-accent={accent ?? undefined}
      tabIndex={-1}
      aria-current={isSelected || undefined}
      aria-busy={writing || undefined}
      data-leaving={rows.leaving[key] !== undefined || undefined}
      // While Ångra shows (not while a tap waits): the ring is filled, the title in text-2 and › hidden by CSS.
      data-undo={entry && !queued ? "on" : undefined}
      data-muted={parentDone || undefined}
      style={rowStyle(rows.leaving[key])}
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
            // The row's new state while its change can be undone; the Ångra and its time are the receipt bar's.
            <UndoMeta text={undo?.text ?? ""} moving={!entry} labels={t} />
          ) : (
            <>
              {parentDone ? (
                <p className="work-card-meta">{a.parentDone}</p>
              ) : (
                <RecordMeta item={item} labels={t} now={now} group={group} />
              )}
              {!parentDone && (
                <WaitingMeta
                  item={item}
                  now={now}
                  dateLocale={t.dateLocale}
                  group={group}
                />
              )}
              {waiting && <WaitingLine text={t.queued} />}
              {note !== undefined && (
                <p className="work-agenda-moved">{note}</p>
              )}
            </>
          )}
        </div>
        {/* Every row that opens a view ends in › (§3, Chevronregeln); while its change can be undone it has none. */}
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
          firstChoice=":is(.work-agenda-menu, .work-agenda-popmenu) .sk-chip"
        />
      )}
    </li>
  );
}
