import { useId, useState } from "react";
import { relativeDue, type DueLocale } from "../../mcp-apps/ui/due";
import { StatusGlyph } from "../../mcp-apps/ui/status-glyph";
import { finePointer } from "../../mcp-apps/ui/shortcuts";
import { UndoMeta } from "../agenda/agenda-undo";
import { taskStatusLabel, type WorkLabels } from "../shared/labels";
import { RowControls } from "../shared/manage-controls";
import type { ManageLabels } from "../shared/manage-labels";
import {
  RowMenuButton,
  RowMenuClose,
  rowMenuHandlers,
} from "../shared/row-menu";
import type { WorkAction } from "../transport/transport";
import type { StepUndo } from "./steps-state";
import { stepActionsLabelsFor } from "./step-actions-labels";

/**
 * One Action under a Step: the Step's checkbox and title, and its Up, Down and Archive in a menu that a long press, a
 * right click, Shift+F10 or the hidden `moreActions` button opens (as a Step's). The box ticks an open Action and unticks a
 * done one, which is dimmed while it is done. A host that can do neither (`onComplete` and `onReopen` absent) shows the
 * state as a mark without a box; with only one of them, the box is read-only in the state the other one would change.
 * Under the title stands one meta line: the due day (red once it has passed, left out when the Action is done) and the
 * note, which gives way with "…". A tick or an untick keeps the row in its place with "Klar" and Ångra for a short while.
 */
export function StepActionRow({
  action,
  index,
  count,
  disabled,
  labels: t,
  manage,
  undo,
  onUndo,
  onExpire,
  onComplete,
  onReopen,
  onMove,
  onArchive,
}: {
  action: WorkAction;
  index: number;
  count: number;
  disabled: boolean;
  labels: WorkLabels;
  manage: ManageLabels;
  /** The tick this row was just given: its meta line says `completed` or `stepReopened` and Ångra stands in the row. */
  undo?: Pick<StepUndo, "id" | "version" | "done">;
  onUndo: () => void;
  onExpire: () => void;
  /** Absent: the host cannot complete an Action, so the row is shown, not ticked. */
  onComplete?: () => void;
  /** Absent: the host cannot open an Action again, so a done Action stays ticked. */
  onReopen?: () => void;
  /** Absent: no Up and Down. */
  onMove?: (delta: -1 | 1) => void;
  /** Absent: no Archive. */
  onArchive?: () => void;
}) {
  const s = stepActionsLabelsFor(t.dateLocale);
  const [open, setOpen] = useState(false);
  const done = action.status === "completed";
  // The server calls an Action that is not done "open"; the row's words and glyph know it as "todo".
  const status = action.status === "open" ? "todo" : action.status;
  const toggle = done ? onReopen : onComplete;
  const hasMenu = Boolean(onMove || onArchive);
  const hasBox = Boolean(onComplete || onReopen);
  // Only a state the check does not say is written out: `in_progress`, `blocked`.
  const state =
    status === "todo" || done ? undefined : taskStatusLabel(t, status);
  // A done Action is not overdue, so it names no day, as a done Task does not.
  const locale: DueLocale = t.dateLocale.toLowerCase().startsWith("sv")
    ? "sv"
    : "en";
  const due = done ? undefined : relativeDue(action.due_at, new Date(), locale);
  const note = action.note?.trim();
  const hasMeta = Boolean(due?.text || note);
  const titleId = useId();
  const stateId = useId();
  const metaId = useId();
  const hintId = useId();
  // The box is named by the title alone; the state, the due day, the note and the menu hint are its description.
  const describedBy =
    [state && stateId, hasMeta && metaId, hasBox && hasMenu && hintId]
      .filter(Boolean)
      .join(" ") || undefined;
  const title = (
    <span className="work-step-action-text">
      <span>
        <span id={titleId}>{action.title}</span>
        {state && (
          <span id={stateId} className="work-step-action-status">
            {state}
          </span>
        )}
      </span>
      {hasMeta && (
        <span id={metaId} className="work-step-action-meta">
          {due?.text && <span data-tone={due.tone}>{due.text}</span>}
          {due?.text && note ? " · " : null}
          {note}
        </span>
      )}
    </span>
  );
  return (
    <li
      className={[
        "work-step-action",
        done && "work-step-action-done",
        undo && "work-step-undoing",
      ]
        .filter(Boolean)
        .join(" ")}
      {...(hasMenu ? rowMenuHandlers(open, setOpen) : {})}
    >
      {hasBox ? (
        <label>
          <input
            type="checkbox"
            className="work-step-check"
            data-manage={`${action.id}:more`}
            aria-keyshortcuts={hasMenu ? "Shift+F10" : undefined}
            aria-labelledby={titleId}
            aria-describedby={describedBy}
            checked={done}
            // Without a way to change this state the box stays as it is and says so, instead of looking disabled.
            aria-readonly={!toggle || undefined}
            disabled={disabled && Boolean(toggle)}
            onChange={(event) => {
              // A box that cannot change is put back at once: the browser has already flipped it, and Preact keeps it.
              if (toggle) toggle();
              else event.currentTarget.checked = done;
            }}
          />
          <StatusGlyph kind="step" status={status} />
          {title}
          {hasMenu && (
            <span id={hintId} className="work-visually-hidden">
              {finePointer() ? s.menuKeys : s.menuHint}
            </span>
          )}
        </label>
      ) : (
        <div className="work-step-read">
          <StatusGlyph
            kind="step"
            status={status}
            label={taskStatusLabel(t, status)}
          />
          {title}
        </div>
      )}
      {undo && (
        // A new tick gets a new key, so its Ångra starts its own time.
        <UndoMeta
          key={`${undo.id}:${undo.version}`}
          text={undo.done ? t.stepDone : t.stepReopened}
          title={action.title}
          labels={t}
          disabled={disabled}
          onUndo={onUndo}
          onExpire={onExpire}
        />
      )}
      {hasMenu && open && (
        <div className="work-step-menu">
          <RowControls
            id={action.id}
            title={action.title}
            index={index}
            count={count}
            disabled={disabled}
            labels={manage}
            onMove={onMove}
            onArchive={onArchive}
          />
          <RowMenuClose label={t.closeMenu} close={() => setOpen(false)} />
        </div>
      )}
      {hasMenu && (
        <RowMenuButton
          label={t.rowMenuButton(action.title)}
          open={() => setOpen(true)}
          firstChoice=".work-step-menu button:not(:disabled)"
        />
      )}
    </li>
  );
}
