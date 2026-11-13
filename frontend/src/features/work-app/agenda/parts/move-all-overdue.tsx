import { useEffect, useRef, useState } from "react";
import { ArrowRightIcon } from "../../../mcp-apps/ui/icons";
import type { WorkLabels } from "../../shared/labels";
import { UNDO_MS } from "../../../mcp-apps/ui/undo-hold";
import { useNearest } from "../agenda-undo";

/**
 * "Flytta N försenade till imorgon" at the foot of the Overdue group. A tap does not write: the button gives way to a
 * question ("Flytta 3 till imorgon?") with "Flytta" and "Avbryt" on the same place, and focus goes to "Flytta".
 * "Avbryt" and Escape bring the button back with focus on it.
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
 * The line after a move-all, "3 flyttade till imorgon" with Ångra beside it, for `UNDO_MS`. The time stands still while
 * the pointer is over it or focus is in it. It is a polite live region and scrolls into view when it shows; when focus
 * was lost with the confirm button, Ångra takes it once the write is done.
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
  const [held, setHeld] = useState(false);
  const left = useRef(UNDO_MS);
  const nearest = useNearest<HTMLParagraphElement>();
  const button = useRef<HTMLButtonElement>(null);
  const focusChecked = useRef(false);
  useEffect(() => {
    if (held) return undefined;
    const since = Date.now();
    const timer = setTimeout(onExpire, left.current);
    return () => {
      clearTimeout(timer);
      left.current -= Date.now() - since;
    };
  }, [held, onExpire]);
  useEffect(() => {
    if (disabled || focusChecked.current) return;
    focusChecked.current = true;
    const active = document.activeElement;
    if (!active || active === document.body) button.current?.focus();
  }, [disabled]);
  return (
    <div
      className="work-agenda-move-undo"
      onPointerEnter={() => setHeld(true)}
      onPointerLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
    >
      <p role="status" ref={nearest}>
        {t.moveAllDone(count)}
      </p>
      <button
        ref={button}
        type="button"
        className="sk-btn--secondary sk-btn--compact"
        disabled={disabled}
        onClick={onUndo}
      >
        {t.agendaUndo}
      </button>
    </div>
  );
}
