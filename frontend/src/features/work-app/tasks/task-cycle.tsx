import { useUndoHold } from "../../mcp-apps/ui/undo-hold";
import type { WorkLabels } from "../shared/labels";

/**
 * The Task view's answer to "Markera klar" on a recurring Task: the server recorded the cycle and opened the
 * Task again for its next date, so the button still says "Markera klar". This line, right under it, says what
 * happened ("Klar · nästa: fre 27 nov") with Ångra, which writes the earlier due date back. It is a polite live
 * region; its time to undo stops while the pointer is over it or focus is in it, and `onExpire` ends it.
 */
export function TaskCycleLine({
  text,
  labels: t,
  disabled,
  onUndo,
  onExpire,
}: {
  text: string;
  labels: WorkLabels;
  disabled: boolean;
  /** Absent where the host cannot write the due date back: the line only says what happened. */
  onUndo?: () => void;
  onExpire: () => void;
}) {
  return (
    <div className="work-task-cycle" {...useUndoHold(true, onExpire).handlers}>
      <p role="status">{text}</p>
      {onUndo && (
        <button
          type="button"
          className="sk-btn--secondary sk-btn--compact"
          disabled={disabled}
          onClick={onUndo}
        >
          {t.agendaUndo}
        </button>
      )}
    </div>
  );
}
