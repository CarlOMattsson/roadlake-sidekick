import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import { fillLabel } from "../agenda/agenda-undo";
import {
  workKindLabel,
  workStatusLabel,
  type WorkLabels,
} from "../shared/labels";
import { frameFor } from "../shared/work-items";
import { OpenChevron } from "../tasks/task-detail-controls";
import {
  TASK_STATUSES,
  domainAccentOf,
  type TaskStatusValue,
  type WorkFrame,
  type WorkItemRecord,
} from "../transport/transport";
import { finePointer } from "../../mcp-apps/ui/shortcuts";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { relativeDue, workDate, type DueTone } from "../../mcp-apps/ui/due";
import { RepeatIcon } from "../../mcp-apps/ui/icons";
import { taskPlaceLabelsFor } from "../tasks/task-place-labels";

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

/**
 * The keys and the long press that open a row's quick choices (designsystem §3 "Snabbval"): `contextmenu` (a
 * long press on touch, a right click), Shift+F10 and the menu key toggle them, and Escape closes them. A context menu
 * the drag handle already took (it prevents the default) is left alone.
 */
export function rowMenuHandlers(open: boolean, set: (open: boolean) => void) {
  return {
    onContextMenu(event: MouseEvent) {
      if (event.defaultPrevented) return;
      event.preventDefault();
      menuUsed();
      forgetMenuButton(event.currentTarget as HTMLElement);
      set(!open);
    },
    onKeyDown(event: KeyboardEvent) {
      const menu =
        event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");
      if (!menu && !(open && event.key === "Escape")) return;
      event.preventDefault();
      const row = event.currentTarget as HTMLElement;
      if (menu) {
        menuUsed();
        forgetMenuButton(row);
      }
      // Escape from inside the menu: the focused choice unmounts, so the control that opened it (the hidden menu button,
      // when that opened it) or else the row's own control takes the focus back.
      else
        (
          menuButtonOf(row) ?? row.querySelector<HTMLElement>("input, button")
        )?.focus();
      set(menu && !open);
    },
  };
}

/** The attribute that marks the hidden menu button which opened its row's menu, so closing can return to it. */
const OPENED_BY_BUTTON = "data-row-menu-via";

/** The row's hidden menu button, if it is the one that opened the menu now open (or last opened). */
export function menuButtonOf(row: Element | null | undefined) {
  return row?.querySelector<HTMLElement>(`[${OPENED_BY_BUTTON}]`) ?? undefined;
}

function forgetMenuButton(row: Element) {
  row.querySelector(`[${OPENED_BY_BUTTON}]`)?.removeAttribute(OPENED_BY_BUTTON);
}

/**
 * The row's menu for a screen reader (designsystem §3 "Snabbval"): a button drawn nowhere (`work-visually-hidden`),
 * last in the row, that opens the same menu as the long press and puts the focus on the menu's first choice. It is out
 * of the Tab order (the keyboard has Shift+F10); Escape or the close button in the menu returns the focus to it.
 * `open` opens the menu, `firstChoice` finds its first choice inside the row.
 */
export function RowMenuButton({
  label,
  open,
  firstChoice,
}: {
  label: string;
  open: () => void;
  firstChoice: string;
}) {
  return (
    <button
      type="button"
      className="work-visually-hidden"
      tabIndex={-1}
      onClick={(event) => {
        const button = event.currentTarget;
        const row = button.closest("li");
        menuUsed();
        button.setAttribute(OPENED_BY_BUTTON, "1");
        // The menu stands in the DOM before the focus goes to its first choice.
        flushSync(open);
        row?.querySelector<HTMLElement>(firstChoice)?.focus();
      }}
    >
      {label}
    </button>
  );
}

/*
 * The long-press tip (designsystem §3 "Listrad"): "Håll inne en uppgift för fler val." stands last in Agenda and
 * Status until the quick choices are first opened, and is gone for good after that. The frame's storage keeps it when
 * the host allows it; the document's `data-row-menu` keeps it for the session when not, and hides a tip that is still
 * drawn (agenda.css) until its list draws again.
 */
const TIP_KEY = "sidekick.rowMenuUsed";
const seen = document.documentElement.dataset;
function menuUsed() {
  seen.rowMenu = "1";
  try {
    localStorage[TIP_KEY] = "1";
  } catch {
    // No storage in this frame: the document keeps the answer for the session.
  }
}

/**
 * The row hint: the long press on touch, the right click and Shift+F10 with a fine pointer. `step` gives the
 * Step's words.
 */
export const rowMenuHint = (t: WorkLabels, step?: boolean) =>
  finePointer()
    ? step
      ? t.stepMenuKeys
      : t.rowMenuKeys
    : step
      ? t.stepMenuHint
      : t.rowMenuHint;

/**
 * The long-press tip, last in a list of Tasks (or under a Task's Steps, `step`), until the quick choices are first
 * opened. One answer for both: a long press learnt on a row is known on a Step. A view with several lists (the Task's
 * Steps and Contacts, a Contact's Projects) shows one tip, the last one in the article, so the same sentence is not
 * repeated down the page: each tip hides itself while another stands after it, and shows again when that one leaves.
 */
export function RowMenuTip({
  labels: t,
  step,
}: {
  labels: WorkLabels;
  step?: boolean;
}) {
  let used = seen.rowMenu;
  try {
    used ||= localStorage[TIP_KEY];
  } catch {
    // No storage: only this session's answer counts.
  }
  if (used) return null;
  return (
    <p
      className="work-row-tip"
      ref={(tip) => {
        const scope: ParentNode = tip?.closest("article") ?? document;
        /** Hides every tip of the scope but the last; `leaving` is a tip that is going and no longer counts. */
        const settle = (leaving?: HTMLElement) => {
          const tips = [
            ...scope.querySelectorAll<HTMLElement>(".work-row-tip"),
          ].filter((other) => other !== leaving);
          tips.forEach((other, index) => {
            other.hidden = index < tips.length - 1;
          });
        };
        settle();
        return () => settle(tip ?? undefined);
      }}
    >
      {rowMenuHint(t, step)}
    </p>
  );
}

/**
 * The status in words for a Task in progress or blocked; "Att göra" and a done Task get none: the ring says done or not
 * done. `word` names a status (the work labels, or the inline labels).
 */
export function rowStatus(
  item: WorkItemRecord,
  word: (status: string) => string,
): string | null {
  return item.kind === "task" &&
    (item.status === "in_progress" || item.status === "blocked")
    ? word(item.status)
    : null;
}

/**
 * The time of a row: "9 dagar försenad" when overdue, else the date as a sentence part ("fre 6 nov", "idag").
 * None for a done or cancelled record, and none under "Idag" for a Task due today, as the group says it; an overdue
 * time always stands.
 */
export function rowDue(
  item: WorkItemRecord,
  now: Date,
  locale: string,
  group?: string | null,
): { text: string; tone: DueTone; at: string } | null {
  if (
    !item.due_at ||
    item.status === "completed" ||
    item.status === "cancelled"
  )
    return null;
  const due = relativeDue(
    item.due_at,
    now,
    locale.startsWith("sv") ? "sv" : "en",
  );
  if (!due.text || (group === "today" && due.tone === "today")) return null;
  return {
    text:
      due.tone === "overdue"
        ? due.text
        : workDate(item.due_at, now, locale, { inline: true }),
    tone: due.tone,
    at: item.due_at,
  };
}

/**
 * The meta of a record row, one builder for the Agenda, Status and the inline cards: one line, the time
 * first, then the status in words, the kind (not for a Task), the "High" marker and the Project last ("9 dagar
 * försenad · Pågår · Renovering av köket"). The status is left out in Status (`inStatus`), whose sections are the
 * statuses. A Project there stands in the Projekt section, which names its kind, so it shows its own status instead
 * ("Aktivt", "Pausat"): a Project's status is not a Task status. The Project stands in both lists, whole or not at all: when the line has no room for the
 * whole name, CSS leaves it and its "·" out, so the row keeps one meta line and nothing is cut; its full name is the
 * text (screen readers) and the title. Each
 * part is a flex item and the "·" before it is drawn in CSS, so a wrapped line never starts or ends with one. The
 * inline cards take the time and the status only (`inlineMeta`).
 */
export function RecordMeta({
  item,
  labels: t,
  now,
  group,
  inStatus,
}: {
  item: WorkItemRecord;
  labels: WorkLabels;
  now: Date;
  /** The agenda group of the row; the meta never repeats it ("idag" under "Idag, …"). */
  group?: string | null;
  inStatus?: boolean;
}) {
  const projectInStatus = inStatus && item.kind === "project";
  const status = projectInStatus
    ? workStatusLabel(t, item.status)
    : inStatus
      ? null
      : rowStatus(item, (s) => workStatusLabel(t, s));
  const kind =
    item.kind === "task" || projectInStatus
      ? null
      : workKindLabel(t, item.kind);
  const marked = item.kind === "task" && item.priority === "high";
  const due = rowDue(item, now, t.dateLocale, group);
  // A Task that repeats says so after its time: "↻ varje månad".
  const repeat =
    item.kind === "task" && item.recurrence
      ? taskPlaceLabelsFor(t.dateLocale).repeatsShort(item.recurrence)
      : null;
  const project = item.project_title;
  if (!status && !kind && !project && !marked && !due && !repeat) return null;
  return (
    <p className="work-card-meta">
      {due ? (
        <span className="work-card-due">
          <time
            dateTime={due.at}
            title={workDate(due.at, now, t.dateLocale, { relative: false })}
            data-tone={due.tone}
          >
            {due.text}
          </time>
        </span>
      ) : null}
      {repeat ? (
        <span className="work-card-repeat">
          <RepeatIcon />
          {repeat}
        </span>
      ) : null}
      {status ? <span className="work-card-status">{status}</span> : null}
      {kind ? <span className="work-card-kind">{kind}</span> : null}
      {marked ? (
        <span className="work-card-priority" data-priority="high">
          {t.priorityLevel.high}
        </span>
      ) : null}
      {project ? (
        <span className="work-card-project" title={project}>
          {project}
        </span>
      ) : null}
    </p>
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
