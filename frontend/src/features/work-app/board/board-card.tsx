import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { fillLabel } from "../agenda/agenda-undo";
import {
  workKindLabel,
  workStatusLabel,
  type WorkLabels,
} from "../shared/labels";
import { RecordMeta } from "../shared/record-meta";
import {
  RowMenuButton,
  menuButtonOf,
  rowMenuHandlers,
  rowMenuHint,
} from "../shared/row-menu";
import { frameFor } from "../shared/work-items";
import { OpenChevron } from "../tasks/task-detail-controls";
import {
  TASK_STATUSES,
  domainAccentOf,
  type TaskStatusValue,
  type WorkFrame,
  type WorkItemRecord,
} from "../transport/transport";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";

/* In the columns layout the handle is the only part that stops the browser from scrolling; the card body still scrolls. */
const handleStyle: CSSProperties = { touchAction: "none", userSelect: "none" };
const draggingStyle: CSSProperties = { opacity: 0.5 };

/**
 * A record's title as a button when it opens a frame, otherwise as plain text. With `hint` the row has quick
 * choices behind a long press or Shift+F10 (designsystem §3 "Snabbval"), and the title says so.
 */
export function RecordTitle({
  item,
  disabled,
  onOpen,
  hint,
}: {
  item: WorkItemRecord;
  disabled: boolean;
  onOpen: (frame: WorkFrame) => void;
  hint?: string;
}) {
  const target = frameFor(item);
  if (!target) return <p className="work-card-title">{item.title}</p>;
  return (
    <button
      type="button"
      disabled={disabled}
      // The whole title, also where the row clamps it (one line while the row's menu is open at large text).
      aria-label={item.title}
      aria-keyshortcuts={hint && "Shift+F10"}
      {...{ "aria-description": hint }}
      onClick={() => onOpen(target)}
    >
      {item.title}
    </button>
  );
}

/** The drag handle's handlers for one card; see `handleFor` in BoardView. */
type DragHandle = {
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerCancel: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
};

/** Window event: a card opened its ⋯ group. The detail is that card's id; the others close theirs. */
const MENU_OPENED = "sidekick-work-card-menu-opened";

/**
 * One record on the board: its status glyph, title, meta line and, for a Task, its quick choices. In "columns" the
 * Task's glyph is the drag handle. In "single" (a narrow phone) the glyph is a done toggle with no drag. The row has
 * no ⋯ (designsystem §3 "Snabbval"): a long press, Shift+F10 or the menu key opens a group inside the card with
 * the four statuses and, when `onReorder` is given, Flytta upp and Flytta ned. `undo` takes the meta line's place
 * while the last change of this card can be undone ("Klar · Ångra").
 */
export function BoardCard({
  item,
  labels: t,
  disabled,
  dragging,
  layout = "columns",
  onOpen,
  onMove,
  onToggleDone,
  onReorder,
  canMoveUp = true,
  canMoveDown = true,
  drag,
  now = new Date(),
  undo,
  queued = false,
  busy = false,
  parentTitle,
  nested,
}: {
  item: WorkItemRecord;
  labels: WorkLabels;
  disabled: boolean;
  dragging: boolean;
  /** "columns" keeps the drag handle; "single" makes the glyph a done toggle, with no drag. */
  layout?: "columns" | "single";
  onOpen: (frame: WorkFrame) => void;
  /** Writes the Task's status when a status is picked in the group. */
  onMove: (card: WorkItemRecord, to: TaskStatusValue) => void;
  /** The glyph in "single" calls it; the caller decides the target status. */
  onToggleDone?: (card: WorkItemRecord) => void;
  /** Moves the Task one place in its column: -1 up, 1 down. Without it the reorder buttons are not shown. */
  onReorder?: (card: WorkItemRecord, step: -1 | 1) => void;
  /** False at the top of the column; the up button is then disabled. */
  canMoveUp?: boolean;
  /** False at the bottom of the column; the down button is then disabled. */
  canMoveDown?: boolean;
  /** The drag handle's handlers; only the "columns" layout has a handle. */
  drag?: DragHandle;
  /** The instant the due date is measured from; defaults to the current time. */
  now?: Date;
  /** The Undo line of this card's last change, shown instead of the meta line. */
  undo?: ReactNode;
  /** A tap of this card waits behind its running write: the card says so. */
  queued?: boolean;
  /** A write of this card is running or waiting. */
  busy?: boolean;
  /** A Step's Task by title when the Task stands elsewhere: its meta is "Steg i: <title>", on two lines. */
  parentTitle?: string;
  /** A Step right after its Task in the same section: indented, its meta "Steg". */
  nested?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  const menuId = useId();
  const accent = domainAccentOf(item.domain_accent);
  const single = layout === "single";
  const task = item.kind === "task";
  // A Step in the single layout (Status) is a row of the Task list: its square check in the ring's column, the title on
  // the titles' x, and one meta line that names its Task.
  const step = item.kind === "step" && single;
  // Only one group is open at a time: opening this one tells every other card to close its group.
  useEffect(() => {
    if (!open) return;
    function closeIfOther(event: Event) {
      if ((event as CustomEvent<string>).detail !== menuId) setOpen(false);
    }
    window.addEventListener(MENU_OPENED, closeIfOther);
    window.dispatchEvent(new CustomEvent(MENU_OPENED, { detail: menuId }));
    return () => window.removeEventListener(MENU_OPENED, closeIfOther);
  }, [open, menuId]);
  /** Opens or closes the group; closing hands focus back to the title, where the keys opened it. */
  function show(next: boolean) {
    setOpen(next);
    if (!next)
      (
        menuButtonOf(row.current) ??
        row.current?.querySelector<HTMLElement>(".work-card-head > :last-child")
      )?.focus();
  }
  function pick(to: TaskStatusValue) {
    // The status the Task already has is shown as pressed, and picking it does nothing.
    if (to === item.status) return;
    // The chosen button unmounts with the menu: focus goes to the hidden menu button or the row's own control first
    //, the same as closing the menu does.
    show(false);
    onMove(item, to);
  }
  const doneLabel = fillLabel(
    item.status === "completed" ? t.agendaReopen : t.agendaComplete,
    { title: item.title },
  );
  return (
    <li
      ref={row}
      className={accent ? "work-card work-accent" : "work-card"}
      data-kind={item.kind === "step" ? "step" : undefined}
      data-nested={nested || undefined}
      // While Ångra shows: the ring is filled, the title in text-2 and › hidden by CSS.
      data-undo={undo ? "on" : undefined}
      data-card-id={item.id}
      data-accent={accent ?? undefined}
      aria-busy={busy ? true : undefined}
      style={dragging ? draggingStyle : undefined}
      {...(task ? rowMenuHandlers(open, show) : {})}
    >
      <div className="work-card-head">
        {task && single && (
          <button
            type="button"
            className="work-card-done"
            disabled={disabled || !onToggleDone}
            aria-label={doneLabel}
            onClick={() => onToggleDone?.(item)}
          >
            {/* The button's label names the action, so the glyph is hidden from AT. */}
            <StatusGlyph kind="task" status={item.status} />
          </button>
        )}
        {step && (
          <button
            type="button"
            className="work-card-done"
            disabled={disabled || !onToggleDone}
            aria-label={doneLabel}
            onClick={() => onToggleDone?.(item)}
          >
            <StatusGlyph kind="step" status={item.status} />
          </button>
        )}
        {task && !single && (
          <button
            type="button"
            className="work-drag-handle"
            disabled={disabled}
            aria-label={t.dragTaskFor(item.title)}
            title={t.dragTaskFor(item.title)}
            aria-keyshortcuts="ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight"
            style={handleStyle}
            onPointerDown={drag?.onPointerDown}
            onPointerMove={drag?.onPointerMove}
            onPointerUp={drag?.onPointerUp}
            onPointerCancel={drag?.onPointerCancel}
            onContextMenu={(event) => event.preventDefault()}
            onKeyDown={drag?.onKeyDown}
          >
            {/* The glyph is the grip: the button's label names the drag, so the glyph is hidden from AT. */}
            <StatusGlyph kind="task" status={item.status} />
          </button>
        )}
        {/* A Project, and a Step on the columns board (it cannot be dragged): its glyph in the lead, so the title and
            the meta line keep the other cards' x. */}
        {(item.kind === "project" || (item.kind === "step" && !single)) && (
          <span className="work-card-glyph">
            <StatusGlyph
              kind={item.kind}
              status={item.status}
              label={workStatusLabel(t, item.status)}
            />
          </span>
        )}
        <RecordTitle
          item={item}
          disabled={disabled}
          onOpen={onOpen}
          hint={task ? rowMenuHint(t) : undefined}
        />
      </div>
      {/* The single layout's rows end in › like every row that opens a view (§3, Chevronregeln); Ångra takes its
          place. */}
      {single && !undo && <OpenChevron />}
      {undo ??
        (step ? (
          // A Step right under its Task has no meta: the indent says
          // it belongs to the row above. Elsewhere it says whose Step it is.
          nested ? null : (
            <p className="work-card-meta work-card-step-of">
              {parentTitle
                ? fillLabel(t.stepOf, { title: parentTitle })
                : workKindLabel(t, "step")}
            </p>
          )
        ) : (
          <RecordMeta item={item} labels={t} now={now} inStatus />
        ))}
      {queued && <span className="sk-queued">{t.queued}</span>}
      {open && (
        <div
          className="work-card-actions"
          role="group"
          aria-label={t.moveListFor(item.title)}
        >
          <div className="work-card-choices">
            {TASK_STATUSES.map((status) => (
              <button
                key={status}
                type="button"
                disabled={disabled}
                aria-pressed={status === item.status}
                onClick={() => pick(status)}
              >
                {workStatusLabel(t, status)}
              </button>
            ))}
          </div>
          {onReorder && (
            <div className="work-card-order">
              <button
                type="button"
                disabled={disabled || !canMoveUp}
                onClick={() => onReorder(item, -1)}
              >
                {t.moveUp}
              </button>
              <button
                type="button"
                disabled={disabled || !canMoveDown}
                onClick={() => onReorder(item, 1)}
              >
                {t.moveDown}
              </button>
            </div>
          )}
        </div>
      )}
      {task && (
        <RowMenuButton
          label={t.rowMenuButton(item.title)}
          open={() => show(true)}
          firstChoice=".work-card-choices button"
        />
      )}
    </li>
  );
}
