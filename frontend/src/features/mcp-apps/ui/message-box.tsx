import type { ReactNode } from "react";

import { buttonClass } from "./button";
import "./message-box.css";

/**
 * The one message box (helhet rule 7): a message about the view that stands at the top of it, in three severities with
 * the same form, the same place and one glyph per severity.
 * - `info` (grey): something to know, no action needed ("Minnet är pausat").
 * - `warning` (amber): something is off and the box offers the way to fix it ("Minnestjänsten är avstängd" +
 *   "Slå på").
 * - `error` (red): something failed; the action is "Försök igen". A failed first read with nothing to show is not a
 *   box but `ErrorNotice` (states.tsx) in place of the content; a write that failed on a row is `ErrorNotice
 *   placement="row"` under that control.
 *
 * `error` is `role="alert"` (announced at once), the others `role="status"`. The action is a compact secondary
 * button, 48 to tap; while `busy` it reads `busyLabel` (when given), is `aria-busy` and does nothing. Text arrives as
 * props, so the caller picks the language.
 */
export type MessageSeverity = "info" | "warning" | "error";

export type MessageAction = {
  label: string;
  onClick: () => void;
  busy?: boolean;
  busyLabel?: string;
};

export type MessageBoxProps = {
  severity: MessageSeverity;
  /** One line in 600: what happened. */
  title: string;
  /** Optional sentence under the title, in body type. */
  children?: ReactNode;
  action?: MessageAction;
  className?: string;
};

function Glyph({ severity }: { severity: MessageSeverity }) {
  return (
    <svg
      className="sk-message__glyph"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {severity === "info" ? (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v6M12 7.5v.01" />
        </>
      ) : (
        <>
          <path d="M12 3.5 21.5 20h-19Z" />
          <path d="M12 10v4.5M12 17.5v.01" />
        </>
      )}
    </svg>
  );
}

export function MessageBox({
  severity,
  title,
  children,
  action,
  className,
}: MessageBoxProps) {
  const busy = action?.busy ?? false;
  return (
    <div
      role={severity === "error" ? "alert" : "status"}
      className={
        className
          ? `sk-message sk-message--${severity} ${className}`
          : `sk-message sk-message--${severity}`
      }
    >
      <Glyph severity={severity} />
      <div className="sk-message__body">
        <p className="sk-message__title">{title}</p>
        {children ? <p className="sk-message__text">{children}</p> : null}
      </div>
      {action ? (
        <button
          type="button"
          className={buttonClass(
            "secondary",
            "sk-btn--compact sk-message__action",
          )}
          aria-busy={busy || undefined}
          aria-disabled={busy || undefined}
          onClick={() => {
            if (!busy) action.onClick();
          }}
        >
          {busy && action.busyLabel ? action.busyLabel : action.label}
        </button>
      ) : null}
    </div>
  );
}
