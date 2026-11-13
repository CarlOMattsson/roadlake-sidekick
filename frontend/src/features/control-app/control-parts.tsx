import { Fragment, useState, type ReactNode } from "react";
import { Notice as StatusNotice } from "../mcp-apps/ui/notice";
import { ErrorNotice } from "../mcp-apps/ui/states";

/** Rows an inline card lists before the rest is behind "Show all". The card never scrolls. */
export const INLINE_ROWS = 3;

/**
 * A message under the heading. Success is a polite status; a failure is an alert, with `retry` when the failed write can
 * be repeated.
 */
export type Notice = {
  tone: "ok" | "error";
  text: string;
  retry?: (() => void) | undefined;
};

/** Success is the family's status line; a failure is the family's write error row (role="alert"). */
export function NoticeLine({
  notice,
  locale,
}: {
  notice: Notice | undefined;
  locale: string;
}) {
  if (!notice) return null;
  return notice.tone === "error" ? (
    <ErrorNotice
      placement="row"
      locale={locale}
      message={notice.text}
      onRetry={notice.retry}
    />
  ) : (
    <StatusNotice tone="success" className="control-notice control-notice-ok">
      {notice.text}
    </StatusNotice>
  );
}

/**
 * One row: a title, a quiet second line, and at most one visible action at the end. The action is a
 * sibling of the text, never inside it, so the whole row is not a button. A `receipt` (what a saved write
 * did) takes the place of the second line as a status and of the action: the row stays where it is. A
 * `receiptAction` (a link to the record the write was on) stands at the end of the row while the receipt does.
 */
export function ControlRow({
  primary,
  secondary,
  receipt,
  receiptAction,
  action,
  below,
}: {
  primary: string;
  secondary?: string;
  receipt?: string;
  receiptAction?: ReactNode;
  action?: ReactNode;
  /** Full-width content under the row's text and action (a confirmation, a panel). */
  below?: ReactNode;
}) {
  return (
    <li className="control-row">
      <div className="control-row-text">
        <span className="control-row-primary">{primary}</span>
        {/* One meta line, cut with an ellipsis at its end; each "·" part is its own span. */}
        {receipt ? (
          <span role="status" className="control-row-secondary">
            {receipt}
          </span>
        ) : secondary ? (
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
      {receipt ? (
        receiptAction ? (
          <div className="control-row-action">{receiptAction}</div>
        ) : null
      ) : action ? (
        <div className="control-row-action">{action}</div>
      ) : null}
      {below ? <div className="control-row-below">{below}</div> : null}
    </li>
  );
}

/**
 * The first INLINE_ROWS rows, with "Show all (N)" for the rest; in the full view (`full`) every row is
 * listed and there is no toggle. Only real rows count toward the limit and N: a receipt row (`isReceipt`, a
 * "Restored" line standing in a place) is always shown where it stands and never opens the toggle. The expansion grows the card in the flow; there is no inner scroll.
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
  wrapMeta = false,
  isReceipt = () => false,
}: {
  items: readonly T[];
  keyOf: (item: T) => string;
  renderRow: (item: T) => ReactNode;
  /** Builds the toggle's label from the number of real rows (receipt rows not counted). */
  showAll: (count: number) => string;
  showFewer: string;
  label: string;
  /** A row that is only a receipt: shown on its place at all times, outside the row limit. */
  isReceipt?: (item: T) => boolean;
  /** The full view lists every row it holds; the three row limit is for the inline card. */
  full?: boolean;
  expanded?: boolean;
  onExpandedChange?: (next: boolean) => void;
  /** Break a row's meta line onto more lines instead of cutting it with an ellipsis (the time must be read whole). */
  wrapMeta?: boolean;
}) {
  const [own, setOwn] = useState(false);
  const expanded = controlled ?? own;
  const realCount = items.filter((item) => !isReceipt(item)).length;
  let realSeen = 0;
  const shown =
    full || expanded
      ? items
      : items.filter((item) => isReceipt(item) || realSeen++ < INLINE_ROWS);
  return (
    <>
      <ul
        className={wrapMeta ? "control-list control-list-wrap" : "control-list"}
        aria-label={label}
      >
        {shown.map((item) => (
          <Fragment key={keyOf(item)}>{renderRow(item)}</Fragment>
        ))}
      </ul>
      {!full && realCount > INLINE_ROWS ? (
        <button
          type="button"
          className="control-more sk-more"
          aria-expanded={expanded}
          onClick={() => {
            setOwn(!expanded);
            onExpandedChange?.(!expanded);
          }}
        >
          {expanded ? showFewer : showAll(realCount)}
        </button>
      ) : null}
    </>
  );
}
