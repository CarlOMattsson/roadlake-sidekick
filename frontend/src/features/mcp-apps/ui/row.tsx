import type { ReactNode } from "react";

import { useRecordRow, type RecordRef } from "./split-layout";
import "./row.css";

/**
 * One list row in an MCP App. The row is an `li` with two sibling controls, never nested:
 * the leading slot (a status glyph or initials) is the quick action `onLeading`, and the body
 * (title, metarad, trailing text, chevron) is the open action `onOpen`. Both are native buttons,
 * so Enter and Space work without extra handlers, and focus order follows the DOM order.
 *
 * A control is only rendered when its handler is given. Without `onLeading` the leading slot is
 * plain content; without `onOpen` the body is plain content. A leading button names its action with `leadingLabel`
 * (a glyph alone has no name) and is held with `leadingDisabled` while its write runs. The chevron is shown only when
 * `navigates` is true. `primary` is never clipped, and `secondary` may wrap. Texts come from the caller, so
 * this component has no labels of its own. `trailing` must be plain text or a chip, never a control.
 *
 * A row that opens (`onOpen`) carries `data-sk-row`, the one hook of the shared pointer feedback (row.css): hover, held
 * and `aria-current` tones. A room's own rows that open carry the same attribute; a row that opens nothing has none.
 */
export type RowProps = {
  leading?: ReactNode;
  primary: string;
  secondary?: ReactNode;
  trailing?: ReactNode;
  navigates?: boolean;
  onLeading?: () => void;
  leadingLabel?: string;
  leadingDisabled?: boolean;
  onOpen?: () => void;
  /** The record `onOpen` opens: beside a split list the row is drawn chosen while it is open (useRecordRow). */
  record?: RecordRef;
};

export function Row({
  leading,
  primary,
  secondary,
  trailing,
  navigates = false,
  onLeading,
  leadingLabel,
  leadingDisabled,
  onOpen,
  record,
}: RowProps) {
  const recordRow = useRecordRow(onOpen ? record : undefined);
  const body = (
    <>
      <span className="sk-row-text">
        <span className="sk-row-primary">{primary}</span>
        {secondary ? (
          <span className="sk-row-secondary">{secondary}</span>
        ) : null}
      </span>
      {trailing ? <span className="sk-row-trailing">{trailing}</span> : null}
      {navigates ? <Chevron /> : null}
    </>
  );

  return (
    <li
      className="sk-row"
      data-navigates={navigates ? "true" : undefined}
      data-sk-row={onOpen ? "" : undefined}
      {...recordRow}
    >
      {onLeading ? (
        <button
          type="button"
          className="sk-row-lead"
          aria-label={leadingLabel}
          disabled={leadingDisabled}
          onClick={onLeading}
        >
          {leading}
        </button>
      ) : leading ? (
        <span className="sk-row-lead">{leading}</span>
      ) : null}
      {onOpen ? (
        <button
          type="button"
          className="sk-row-open"
          data-sk-open=""
          onClick={onOpen}
        >
          {body}
        </button>
      ) : (
        <div className="sk-row-open">{body}</div>
      )}
    </li>
  );
}

function Chevron() {
  return (
    <svg
      className="sk-row-chevron"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}
