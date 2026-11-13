import { useState } from "react";
import { ChevronDownIcon } from "../../mcp-apps/ui/icons";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { workStatusLabel, type WorkLabels } from "../shared/labels";
import { UndoMeta } from "../agenda/agenda-undo";
import { RowControls } from "../shared/manage-controls";
import type { ManageLabels } from "../shared/manage-labels";
import { StepActions } from "../steps/step-actions";
import {
  RowMenuButton,
  RowMenuClose,
  rowMenuHandlers,
  rowMenuHint,
} from "../shared/row-menu";
import { stepActionsLabelsFor } from "../steps/step-actions-labels";
import type { StepUndo } from "../steps/steps-state";
import type { WorkStep, WorkTransport } from "../transport/transport";

/** The mark of a Step the host cannot tick: a dot for an open Step, a tick without a box for a done one. Not a control. */
function StepReadMark({ done, label }: { done: boolean; label: string }) {
  return (
    <svg
      className="sk-status-glyph work-step-mark"
      viewBox="0 0 16 16"
      focusable="false"
      role="img"
      aria-label={label}
      data-glyph={done ? "step-read-check" : "step-read-dot"}
    >
      {done ? (
        <path d="M4.2 8.4L6.9 11L11.8 5.4" />
      ) : (
        <circle cx={8} cy={8} r={1.75} />
      )}
    </svg>
  );
}

/**
 * One Step of the list: the checkbox and the title, and the Step's Actions under the title. A long press (touch), a
 * right click, Shift+F10 or the menu key on the Step opens its menu (as Work's rows; the ⋯ is gone): one row of
 * buttons under the title, Up, Down and Archive, and × at its end, which closes it as Escape does. A Step that has
 * Actions says how many under its title; that count opens and closes the list.
 * The check says so to a screen reader (aria-keyshortcuts, aria-description). The menu stays open after a move, so
 * the focus rule keeps the moved row's Up or Down button.
 */
export function StepRow({
  step,
  index,
  count,
  listBusy,
  transport,
  labels: t,
  manage,
  onToggle,
  undo,
  onUndo,
  onExpire,
  onMove,
  onArchive,
  actions,
  onActionCount,
}: {
  step: WorkStep;
  index: number;
  count: number;
  listBusy: boolean;
  transport: WorkTransport;
  labels: WorkLabels;
  manage: ManageLabels;
  /** Absent: the Step is shown, not checked (the host cannot complete it). */
  onToggle?: (step: WorkStep) => void;
  /** The check this row was just given: its meta line says "Klar" or "Öppen igen" and Ångra stands in the row. */
  undo?: StepUndo;
  onUndo: () => void;
  onExpire: () => void;
  /** Absent: no Up and Down. */
  onMove?: (delta: -1 | 1) => void;
  /** Absent: no Archive. */
  onArchive?: () => void;
  /** False: no Actions under the Step (no count to open them). */
  actions: boolean;
  /** The Step's Actions were read or changed; `count` is how many are active and `done` how many of them are done. */
  onActionCount: (count: number, done: number) => void;
}) {
  const [open, setOpen] = useState(false);
  // The Step's Actions open from the count under its title; they stay open until that button closes them.
  const [actionsOpen, setActionsOpen] = useState(false);
  const hasMenu = Boolean(onMove || onArchive);
  // A Step known to have no Actions shows no count; while they are open the button stays, so archiving the last
  // Action does not take away the way to close them.
  const actionCount = step.action_count ?? 0;
  const showCount = actions && (actionsOpen || actionCount > 0);
  const s = stepActionsLabelsFor(t.dateLocale);
  return (
    <li
      className={
        [
          step.status === "completed" && "work-step-done",
          undo && "work-step-undoing",
        ]
          .filter(Boolean)
          .join(" ") || undefined
      }
      {...(hasMenu ? rowMenuHandlers(open, setOpen) : {})}
    >
      {onToggle ? (
        <label>
          {/* The native box is kept for its semantics and keys, but drawn as the app's Step square in the text
              colour (Chromium's blue box was the only system control on the screen); the input covers the whole label. */}
          <input
            type="checkbox"
            className="work-step-check"
            data-manage={`${step.id}:more`}
            aria-keyshortcuts={hasMenu ? "Shift+F10" : undefined}
            {...(hasMenu ? { "aria-description": rowMenuHint(t, true) } : {})}
            checked={step.status === "completed"}
            disabled={listBusy}
            onChange={() => onToggle(step)}
          />
          <StatusGlyph kind="step" status={step.status} />
          <span>{step.title}</span>
        </label>
      ) : (
        // The host cannot tick a Step: it is text with its state in words, not a box that looks pressable. An open Step has
        // a neutral dot, a done one a bare tick (the muted tick of the done ring, without its frame).
        <div className="work-step-read">
          <StepReadMark
            done={step.status === "completed"}
            label={workStatusLabel(t, step.status)}
          />
          <span>{step.title}</span>
        </div>
      )}
      {undo && (
        // A new check gets a new key, so its Ångra starts its own time.
        <UndoMeta
          key={`${undo.id}:${undo.version}`}
          text={undo.done ? t.stepDone : t.stepReopened}
          labels={t}
          disabled={listBusy}
          onUndo={onUndo}
          onExpire={onExpire}
        />
      )}
      {showCount && (
        <button
          type="button"
          className="work-step-actions-open"
          aria-expanded={actionsOpen}
          onClick={() => setActionsOpen((value) => !value)}
        >
          {s.countMeta(actionCount, step.action_done_count)}
          <ChevronDownIcon size={16} />
        </button>
      )}
      {hasMenu && open && (
        <div className="work-step-menu">
          <RowControls
            id={step.id}
            title={step.title}
            index={index}
            count={count}
            disabled={listBusy}
            labels={manage}
            onMove={onMove}
            onArchive={onArchive}
          />
          <RowMenuClose label={t.closeMenu} close={() => setOpen(false)} />
        </div>
      )}
      {actions && (
        <StepActions
          step={step}
          transport={transport}
          labels={t}
          open={actionsOpen}
          onCount={onActionCount}
        />
      )}
      {hasMenu && (
        <RowMenuButton
          label={t.rowMenuButton(step.title)}
          open={() => setOpen(true)}
          firstChoice=".work-step-menu button:not(:disabled)"
        />
      )}
    </li>
  );
}
