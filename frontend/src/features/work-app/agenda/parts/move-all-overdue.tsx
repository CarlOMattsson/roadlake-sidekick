import { useEffect, useRef, useState } from "react";
import { ArrowRightIcon } from "../../../mcp-apps/ui/icons";
import type { WorkLabels } from "../../shared/labels";

/**
 * `moveAllOverdue` at the foot of the Overdue group. A tap does not write: the button gives way to a
 * question (`moveAllConfirm`) with `moveAllConfirmYes` and `cancel` on the same place, and focus goes to `moveAllConfirmYes`.
 * `cancel` and Escape bring the button back with focus on it.
 */
export function MoveAllOverdue({
  labels: t,
  count,
  disabled,
  onMove,
}: {
  labels: WorkLabels;
  count: number;
  disabled: boolean;
  onMove: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  // Cancelling hands focus back to the button; confirming does not (the group is about to change).
  const cancelled = useRef(false);
  function cancel() {
    cancelled.current = true;
    setAsking(false);
  }
  useEffect(() => {
    if (asking) confirm.current?.focus();
    else if (cancelled.current) {
      cancelled.current = false;
      trigger.current?.focus();
    }
  }, [asking]);
  // Escape leaves the question while it is shown, wherever focus is on the page.
  useEffect(() => {
    if (!asking) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [asking]);
  if (!asking)
    return (
      <button
        ref={trigger}
        type="button"
        className="work-agenda-move-all sk-action-row"
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        <ArrowRightIcon />
        {t.moveAllOverdue(count)}
      </button>
    );
  return (
    <div className="work-agenda-move-ask">
      <p>{t.moveAllConfirm(count)}</p>
      <div className="work-agenda-move-ask-actions">
        <button
          ref={confirm}
          type="button"
          className="sk-btn--primary"
          disabled={disabled}
          onClick={() => {
            setAsking(false);
            onMove();
          }}
        >
          {t.moveAllConfirmYes}
        </button>
        <button
          type="button"
          className="sk-btn--quiet"
          disabled={disabled}
          onClick={cancel}
        >
          {t.cancel}
        </button>
      </div>
    </div>
  );
}
