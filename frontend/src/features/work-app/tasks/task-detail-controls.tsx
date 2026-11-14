import { useEffect, useRef, useState, type ReactNode } from "react";
import "../contacts/contacts.css";
import { isCompleteDate } from "../shared/fields";
import { hierarchyDetailLabelsFor } from "../hierarchy/hierarchy-detail-labels";
import { taskStatusLabel, type WorkLabels } from "../shared/labels";
import { ChevronDownIcon, ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { ownerEndOfDay } from "../../mcp-apps/ui/due";
import { triageDueAt } from "../shared/work-items";
import { useUndoHold } from "../../mcp-apps/ui/undo-hold";

/** The ⋯ is the one shared glyph of mcp-apps/ui/icons.tsx. */
export { MoreIcon } from "../../mcp-apps/ui/icons";

/** The statuses the Task's status chip offers. `completed` is the primary button `markDone`, not a menu entry. */
const OPEN_STATUSES = ["todo", "in_progress", "blocked"] as const;
export type OpenTaskStatus = (typeof OPEN_STATUSES)[number];

/**
 * The Task's property chips under its title (design system §3, egenskapschip): the due date (the date and how late it is, with ⌄)
 * and the status (`todo` with ⌄), each a 40 high pill with a 44 target. The date chip opens the
 * quick choices Idag, Imorgon, Nästa vecka and Välj datum under the row; every choice is one write through `onDue`
 * (update_task with due_at, to 23:59 in the owner zone on the chosen day). The status chip opens a menu with ✓ on the current
 * status; a choice writes through `onStatus`. Only one panel is open at a time, and Escape closes it and returns focus
 * to its chip. `children` is the date sentence and `sentence` the same words as text, for the chip's name.
 * A chip is drawn only when its handler is given: a host that cannot write the date or the status leaves it out,
 * and `done` (Markera klar) stays.
 */
export function TaskProps({
  hasDue,
  busy,
  status,
  labels: t,
  onDue,
  onStatus,
  sentence,
  done,
  children,
}: {
  hasDue: boolean;
  busy: boolean;
  status: string;
  labels: WorkLabels;
  onDue?: (dueAt: string) => void;
  onStatus?: (status: OpenTaskStatus) => void;
  sentence?: string;
  /** `markDone` or `reopenTask`, last in the control row. */
  done?: ReactNode;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState<"due" | "status">();
  const [choosing, setChoosing] = useState(false);
  const dueChip = useRef<HTMLButtonElement>(null);
  const statusChip = useRef<HTMLButtonElement>(null);
  const dateInput = useRef<HTMLInputElement>(null);
  const dl = hierarchyDetailLabelsFor(t.dateLocale);
  useEffect(() => {
    if (choosing) dateInput.current?.focus();
  }, [choosing]);
  function close(refocus: boolean) {
    if (refocus) (open === "status" ? statusChip : dueChip).current?.focus();
    setOpen(undefined);
    setChoosing(false);
  }
  function toggle(panel: "due" | "status") {
    setChoosing(false);
    setOpen(open === panel ? undefined : panel);
  }
  function choose(dueAt: string) {
    close(false);
    onDue?.(dueAt);
  }
  const now = new Date();
  const dueName = hasDue ? t.changeDue : t.addDue;
  return (
    <KeyScope
      className="work-task-props"
      onEscape={open ? () => close(true) : undefined}
    >
      {onDue && (
        <button
          ref={dueChip}
          type="button"
          className="sk-chip work-prop-chip"
          aria-label={hasDue && sentence ? `${dueName}: ${sentence}` : dueName}
          aria-expanded={open === "due"}
          disabled={busy}
          onClick={() => toggle("due")}
        >
          <span>{hasDue && children ? children : dueName}</span>
          <ChevronDownIcon size={16} />
        </button>
      )}
      {onStatus && (
        <button
          ref={statusChip}
          type="button"
          className="sk-chip work-prop-chip"
          aria-label={`${dl.changeStatus}: ${taskStatusLabel(t, status)}`}
          aria-expanded={open === "status"}
          disabled={busy}
          onClick={() => toggle("status")}
        >
          <span>{taskStatusLabel(t, status)}</span>
          <ChevronDownIcon size={16} />
        </button>
      )}
      {done}
      {onDue && open === "due" && (
        <div
          role="group"
          aria-label={dueName}
          className="work-task-due-choices"
        >
          <button
            type="button"
            className="sk-chip"
            disabled={busy}
            onClick={() => choose(triageDueAt(now, "today"))}
          >
            {t.dueToday}
          </button>
          <button
            type="button"
            className="sk-chip"
            disabled={busy}
            onClick={() => choose(triageDueAt(now, "tomorrow"))}
          >
            {dl.dueTomorrow}
          </button>
          <button
            type="button"
            className="sk-chip"
            disabled={busy}
            onClick={() => choose(triageDueAt(now, "nextWeek"))}
          >
            {t.dueNextWeek}
          </button>
          <button
            type="button"
            className="sk-chip"
            disabled={busy}
            aria-expanded={choosing}
            onClick={() => setChoosing(!choosing)}
          >
            {t.rescheduleDate}
          </button>
          {choosing && (
            <input
              ref={dateInput}
              type="date"
              aria-label={t.rescheduleDate}
              disabled={busy}
              onChange={(event) => {
                const day = event.target.value;
                if (isCompleteDate(day)) choose(ownerEndOfDay(day));
              }}
            />
          )}
        </div>
      )}
      {onStatus && open === "status" && (
        <div
          role="group"
          aria-label={t.status}
          className="work-contact-menu work-status-menu"
        >
          {OPEN_STATUSES.map((value) => (
            <button
              key={value}
              type="button"
              className="work-contact-menu-item"
              aria-pressed={value === status}
              disabled={busy}
              onClick={() => {
                close(true);
                if (value !== status) onStatus?.(value);
              }}
            >
              {taskStatusLabel(t, value)}
              {value === status && <span aria-hidden="true">✓</span>}
            </button>
          ))}
        </div>
      )}
    </KeyScope>
  );
}

/**
 * The › of a row whose only handling is to open (design system §3, Chevronregeln): the shared glyph of icons.tsx in a
 * 44 px box that ends on the content edge, so its centre is 38 from the edge, as every trailing icon. Decorative; the
 * row's button names the target and its cover takes the tap.
 */
export function OpenChevron() {
  return (
    <span className="work-open-chevron" aria-hidden="true">
      <ChevronRightIcon />
    </span>
  );
}

/**
 * The Ångra of a detail row (design system §3, Tillstånd, Ångra): a compact secondary button in the row's trailing
 * slot, level with the title line, while the meta line says what happened (`completed`, `linkRemoved`).
 */
export function RowUndo({
  label,
  disabled,
  onUndo,
  onExpire,
}: {
  label: string;
  disabled: boolean;
  onUndo: () => void;
  onExpire: () => void;
}) {
  return (
    <button
      type="button"
      className="sk-btn--secondary sk-btn--compact"
      disabled={disabled}
      onClick={onUndo}
      {...useUndoHold(true, onExpire).handlers}
    >
      {label}
    </button>
  );
}
