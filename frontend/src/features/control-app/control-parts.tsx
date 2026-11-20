import { Fragment, type ReactNode } from "react";
import { OpenLink } from "../mcp-apps/ui/open-link";
import { ErrorNotice } from "../mcp-apps/ui/states";
import type { ControlLabels } from "./labels";

/** Rows an inline card lists before the rest is behind its open link. The card never scrolls. */
export const INLINE_ROWS = 3;

/** A failed write under the heading or in its row, with `retry` when the failed write can be repeated. */
export type Notice = {
  text: string;
  retry?: (() => void) | undefined;
};

/** A failure is the family's write error row (role="alert"). A saved write is not a notice but a receipt (ui/receipt). */
export function NoticeLine({
  notice,
  locale,
}: {
  notice: Notice | undefined;
  locale: string;
}) {
  if (!notice) return null;
  return (
    <ErrorNotice
      placement="row"
      locale={locale}
      message={notice.text}
      onRetry={notice.retry}
    />
  );
}

/**
 * One row: a title, a quiet second line, and at most one visible action at the end. The action is a
 * sibling of the text, never inside it, so the whole row is not a button. What a saved write did is not said in the
 * row but in the view's receipt bar.
 */
export function ControlRow({
  primary,
  secondary,
  action,
  stackedAction = false,
  below,
}: {
  primary: string;
  secondary?: string;
  action?: ReactNode;
  /** Several buttons: the action stands under the text, side by side, not in the end column that fits one word. */
  stackedAction?: boolean;
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
      {action ? (
        <div
          className={
            stackedAction
              ? "control-row-action control-row-action--stacked"
              : "control-row-action"
          }
        >
          {action}
        </div>
      ) : null}
      {below ? <div className="control-row-below">{below}</div> : null}
    </li>
  );
}

/**
 * The rows of a list. With a `limit` (the inline card: INLINE_ROWS) only the first rows are listed and the rest is behind
 * the card's open link (`ViewOpenLink`); without one (the full view, or an inline card that cannot open) every row is
 * listed. The card never scrolls inside itself. `renderRow` builds one row.
 */
export function RowList<T>({
  items,
  keyOf,
  renderRow,
  label,
  limit,
  wrapMeta = false,
}: {
  items: readonly T[];
  keyOf: (item: T) => string;
  renderRow: (item: T) => ReactNode;
  label: string;
  limit?: number;
  /** Break a row's meta line onto more lines instead of cutting it with an ellipsis (the time must be read whole). */
  wrapMeta?: boolean;
}) {
  const shown = limit === undefined ? items : items.slice(0, limit);
  return (
    <ul
      className={wrapMeta ? "control-list control-list-wrap" : "control-list"}
      aria-label={label}
    >
      {shown.map((item) => (
        <Fragment key={keyOf(item)}>{renderRow(item)}</Fragment>
      ))}
    </ul>
  );
}

/**
 * How many rows an inline card lists: INLINE_ROWS where the card can open the full view (so the rest is behind its
 * link), else all of them. The full view lists every row.
 */
export function rowLimit(
  full: boolean,
  onOpenFull: (() => void) | undefined,
): number | undefined {
  return !full && onOpenFull ? INLINE_ROWS : undefined;
}

/**
 * The inline card's one main link, last in the card: "Öppna Borttaget ›", then "· 4 till" for the rows it does not show.
 * Nothing in the full view or where the card has no way to open it.
 */
export function ViewOpenLink({
  labels,
  view,
  hidden = 0,
  moreRead = false,
  full,
  onOpenFull,
}: {
  labels: ControlLabels;
  view: keyof ControlLabels["views"];
  /** Rows the card does not list. */
  hidden?: number;
  /** The server holds rows beyond the ones read, so `hidden` is "at least". */
  moreRead?: boolean;
  full: boolean;
  onOpenFull: (() => void) | undefined;
}) {
  if (full || !onOpenFull) return null;
  return (
    <OpenLink
      label={labels.openView(labels.views[view])}
      {...(hidden > 0 ? { more: labels.moreRows(hidden, moreRead) } : {})}
      onOpen={onOpenFull}
    />
  );
}
