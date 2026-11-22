import { decisionLabelsFor } from "./decision-labels";
import "./tokens.css";
import "./trust-note.css";

/**
 * What a check found about a suggestion (or a report) that the owner should see before acting on it. Two levels, both
 * amber and both with ⚠ and words, so colour never carries the meaning alone and red stays for failure, overdue and
 * delete:
 * - `unsure`: "Kontrollen var osäker" and the reason. The suggestion keeps its buttons but is never part of a group
 *   approval.
 * - `suspicious`: "Misstänkt förslag", framed in the warning line and the reason in one sentence. The card it sits on
 *   offers no Approve (DecisionCard).
 *
 * `role="note"`: it belongs to the card it stands on and is read with it, not announced on its own. `title` replaces
 * the level's heading where the thing checked is not a suggestion ("Rapporten var osäker"). The reason is the server's
 * sentence in the app's language; it is plain text.
 */
export type TrustNoteState = "unsure" | "suspicious";

export function TrustNote({
  state,
  reason,
  locale,
  title,
  flow = "block",
  className,
}: {
  state: TrustNoteState;
  reason?: string;
  locale: string;
  title?: string;
  /** `block`: the heading, then the reason on its own line. `run`: one run "Heading: reason", for an inline card. */
  flow?: "block" | "run";
  className?: string;
}) {
  const t = decisionLabelsFor(locale);
  return (
    <div
      role="note"
      data-trust={state}
      data-flow={flow}
      className={
        className
          ? `sk-trust sk-trust--${state} ${className}`
          : `sk-trust sk-trust--${state}`
      }
    >
      <svg
        className="sk-trust__glyph"
        viewBox="0 0 24 24"
        width="20"
        height="20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M12 3.5 21.5 20h-19Z" />
        <path d="M12 10v4.5M12 17.5v.01" />
      </svg>
      <p className="sk-trust__text">
        <span className="sk-trust__title">{title ?? t.trust[state]}</span>
        {reason ? (
          <>
            <span className="sk-trust__sep">: </span>
            <span className="sk-trust__reason">{reason}</span>
          </>
        ) : null}
      </p>
    </div>
  );
}
