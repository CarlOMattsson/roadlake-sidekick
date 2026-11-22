import type { ShoppingLabels } from "../labels";
import type { ShoppingDetail, ShoppingItem } from "../transport";
import { MessageBox } from "../../mcp-apps/ui/message-box";
import { intoView } from "./helpers";

/**
 * The view's notices at its top: a failure the list cannot show on a row (a read, a batch add, an Ångra whose row is
 * gone), with "Try again", and a conflict on a row the list no longer has. A failure of a drawn row stays under that
 * row: a row gone from the list, or folded away under "Köpta" or past the card's budget, has its failure here instead.
 * The create field shows its own.
 */
export function ViewNotices({
  labels: t,
  error,
  conflict,
  undoFailure,
  items,
  drawnRows,
  detail,
  busy,
  onRetry,
}: {
  labels: ShoppingLabels;
  error: { rowId: string | null; change?: boolean } | null;
  conflict: { rowId: string | null } | null;
  /** A failed Ångra whose row is gone: its own words. */
  undoFailure: { id: string; message: string } | null;
  items: readonly ShoppingItem[];
  /** The ids of the rows the view draws now. */
  drawnRows: ReadonlySet<string>;
  detail?: ShoppingDetail;
  busy: boolean;
  onRetry: () => void;
}) {
  const viewError =
    error !== null &&
    error.rowId !== "add" &&
    (error.rowId === null || !drawnRows.has(error.rowId));
  const failedItem = error?.rowId
    ? items.find((item) => item.id === error.rowId)
    : undefined;
  const title =
    error?.rowId && undoFailure?.id === error.rowId
      ? undoFailure.message
      : failedItem && !error?.change
        ? t.markFailed(failedItem.name, !failedItem.purchased)
        : t.failedTitle;
  return (
    <>
      {viewError && (
        <div ref={intoView}>
          <MessageBox
            severity="error"
            title={title}
            action={{ label: t.retry, busy, onClick: onRetry }}
          />
        </div>
      )}
      {conflict &&
        !detail?.items.some((item) => item.id === conflict.rowId) && (
          <div ref={intoView}>
            <MessageBox severity="warning" title={t.conflictTitle}>
              {t.conflictText}
            </MessageBox>
          </div>
        )}
    </>
  );
}
