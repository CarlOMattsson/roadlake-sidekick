import { Fragment, useState, type ReactNode } from "react";
import { Notice as StatusNotice } from "../mcp-apps/ui/notice";

/** Rows an inline card lists before the rest is behind "Show all". The card never scrolls. */
export const INLINE_ROWS = 3;

/** A message under the heading. Success is a polite status; a failure is an alert. */
export type Notice = { tone: "ok" | "error"; text: string };

/** Success is the family's status line; a failure is the family's alert box (role="alert"). */
export function NoticeLine({ notice }: { notice: Notice | undefined }) {
  if (!notice) return null;
  return notice.tone === "error" ? (
    <p role="alert" className="control-notice control-notice-error">
      {notice.text}
    </p>
  ) : (
    <StatusNotice tone="success" className="control-notice control-notice-ok">
      {notice.text}
    </StatusNotice>
  );
}

/**
 * One row: a title, a quiet second line, and at most one visible action at the end. The action is a
 * sibling of the text, never inside it, so the whole row is not a button.
 */
export function ControlRow({
  primary,
  secondary,
  action,
  below,
}: {
  primary: string;
  secondary?: string;
  action?: ReactNode;
  /** Full-width content under the row's text and action (a confirmation, a panel). */
  below?: ReactNode;
}) {
  return (
    <li className="control-row">
      <div className="control-row-text">
        <span className="control-row-primary">{primary}</span>
        {/* One meta line, cut with an ellipsis at its end; each "·" part is its own span. */}
        {secondary ? (
          <span className="control-row-secondary">
            {secondary.split(" · ").map((part, i) => (
              <Fragment key={i}>
                {i ? " " : null}
                <span>{i ? `· ${part}` : part}</span>
              </Fragment>
            ))}
          </span>
        ) : null}
      </div>
      {action ? <div className="control-row-action">{action}</div> : null}
      {below ? <div className="control-row-below">{below}</div> : null}
    </li>
  );
}

/**
 * The first INLINE_ROWS rows, with "Show all (N)" for the rest; in the full view (`full`) every row is
 * listed and there is no toggle. The expansion grows the card in the flow; there is no inner scroll.
 * `renderRow` builds one row. The choice belongs to the card
 * (`expanded` with `onExpandedChange`), so it survives a switch to another tab and back. Without
 * them the list keeps the choice itself.
 */
export function RowList<T>({
  items,
  keyOf,
  renderRow,
  showAll,
  showFewer,
  label,
  full = false,
  expanded: controlled,
  onExpandedChange,
}: {
  items: readonly T[];
  keyOf: (item: T) => string;
  renderRow: (item: T) => ReactNode;
  showAll: (count: number) => string;
  showFewer: string;
  label: string;
  /** The full view lists every row it holds; the three row limit is for the inline card. */
  full?: boolean;
  expanded?: boolean;
  onExpandedChange?: (next: boolean) => void;
}) {
  const [own, setOwn] = useState(false);
  const expanded = controlled ?? own;
  const shown = full || expanded ? items : items.slice(0, INLINE_ROWS);
  return (
    <>
      <ul className="control-list" aria-label={label}>
        {shown.map((item) => (
          <Fragment key={keyOf(item)}>{renderRow(item)}</Fragment>
        ))}
      </ul>
      {!full && items.length > INLINE_ROWS ? (
        <button
          type="button"
          className="control-more sk-btn--quiet"
          aria-expanded={expanded}
          onClick={() => {
            setOwn(!expanded);
            onExpandedChange?.(!expanded);
          }}
        >
          {expanded ? showFewer : showAll(items.length)}
        </button>
      ) : null}
    </>
  );
}
