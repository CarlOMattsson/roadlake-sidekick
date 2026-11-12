import type { ReactNode } from "react";

import { buttonClass } from "./button";
import "./tokens.css";
import "./family.css";

/**
 * The family's status line: a message, then at most one action. `role="status"` is a polite live
 * region, so a screen reader announces it without taking focus. Failures are not notices: they are
 * `ErrorNotice` (states.tsx), which is `role="alert"`.
 *
 * `tone` tints it: `success` for a confirmation, `warning` for a caution, none for plain information.
 * `sticky` rests it at the foot of the view while a list scrolls (`--sk-notice-bottom` lifts it clear
 * of the host's reply field in fullscreen).
 */
export function Notice({
  tone,
  sticky = false,
  className,
  children,
  action,
}: {
  tone?: "success" | "warning";
  sticky?: boolean;
  className?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  const classes = [
    "sk-notice",
    tone ? `sk-notice--${tone}` : "",
    sticky ? "sk-notice--sticky" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div role="status" className={classes}>
      <span className="sk-notice__message">{children}</span>
      {action}
    </div>
  );
}

/**
 * The one Undo line: "what happened" and an "Undo" button, the same look and place everywhere (the
 * foot of the list that changed). The button is secondary and 44 px high. While the undo is written
 * the caller passes `busy` and the button is disabled.
 */
export function UndoNotice({
  message,
  undoLabel,
  onUndo,
  busy = false,
  sticky = true,
  className,
}: {
  message: ReactNode;
  undoLabel: string;
  onUndo: () => void;
  busy?: boolean;
  sticky?: boolean;
  className?: string;
}) {
  return (
    <Notice
      tone="success"
      sticky={sticky}
      className={className}
      action={
        <button
          type="button"
          className={buttonClass("secondary")}
          disabled={busy}
          onClick={onUndo}
        >
          {undoLabel}
        </button>
      }
    >
      {message}
    </Notice>
  );
}
