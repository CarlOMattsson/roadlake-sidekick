import { useEffect, useRef, useState } from "react";
import { ArrowRightIcon } from "../../../mcp-apps/ui/icons";
import type { WorkLabels } from "../../shared/labels";
import { useUndoHold } from "../../../mcp-apps/ui/undo-hold";
import { useNearest } from "../agenda-undo";

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

/**
 * The line after a move-all, `moveAllDone` with Ångra beside it, for `UNDO_MS`. The time stands still while
 * the pointer is over it. Focus does not hold it: Ångra takes focus when the confirm button's was lost, and a hold by
 * focus would never let the time run out. It is a polite live region and scrolls into view when it shows. When the
 * time is up with focus in it, focus goes to the Overdue group's button, or to the heading.
 */
export function MoveAllUndo({
  labels: t,
  count,
  disabled,
  onUndo,
  onExpire,
}: {
  labels: WorkLabels;
  count: number;
  disabled: boolean;
  onUndo: () => void;
  onExpire: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const { held, handlers } = useUndoHold(true, () => {
    const node = box.current;
    if (node?.contains(document.activeElement)) {
      const view = node.closest("article");
      (
        view?.querySelector<HTMLElement>(".work-agenda-move-all") ??
        view?.querySelector<HTMLElement>("h2")
      )?.focus({ preventScroll: true });
    }
    onExpire();
  });
  const nearest = useNearest<HTMLParagraphElement>();
  const button = useRef<HTMLButtonElement>(null);
  const focusChecked = useRef(false);
  useEffect(() => {
    if (disabled || focusChecked.current) return;
    focusChecked.current = true;
    const active = document.activeElement;
    if (!active || active === document.body) button.current?.focus();
  }, [disabled]);
  return (
    <div
      ref={box}
      className="work-agenda-move-undo"
      // The time line under Ångra stands still while the countdown does.
      data-held={held ? "" : undefined}
      onPointerEnter={handlers.onPointerEnter}
      onPointerLeave={handlers.onPointerLeave}
    >
      <p role="status" ref={nearest}>
        {t.moveAllDone(count)}
      </p>
      <button
        ref={button}
        type="button"
        className="sk-btn--secondary sk-btn--compact sk-undo-time"
        disabled={disabled}
        onClick={onUndo}
      >
        {t.agendaUndo}
      </button>
    </div>
  );
}
