import { useUndoHold } from "../../mcp-apps/ui/undo-hold";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { ShoppingLabels } from "../labels";
import { intoView } from "./helpers";
import type { TrashedItem } from "./use-item-trash";

/** What a receipt row reads from the view: the state of the write and the actions it calls. */
export type TrashReceiptEnv = {
  labels: ShoppingLabels;
  busy: boolean;
  conflict: { rowId: string | null } | null;
  error: { rowId: string | null } | null;
  failedWrite: (() => void) | null;
  onRestore: (receipt: TrashedItem) => void;
  /** The time to undo is up: the receipt goes. */
  onRelease: (id: string) => void;
};

/**
 * One deleted item's receipt (designsystem §3 Ångra): the line "Borttagen: name" and its Undo, which runs out after
 * the family's time to undo and stands still while the pointer is over it or focus is in it. A failed Undo says so
 * in the row and offers Try again with the same key.
 */
function TrashReceiptRow({
  receipt,
  env,
}: {
  receipt: TrashedItem;
  env: TrashReceiptEnv;
}) {
  const { labels: t } = env;
  const { item } = receipt;
  const hold = useUndoHold(true, () => env.onRelease(item.id));
  return (
    <li className="shopping-trash-receipt" aria-busy={env.busy || undefined}>
      <div className="shopping-toolbar">
        <p role="status" className="shopping-trash-line">
          {t.itemTrashed(item.name)}
        </p>
        <button
          type="button"
          className="sk-btn--secondary sk-btn--compact sk-undo-time shopping-undo"
          disabled={env.busy}
          aria-label={t.undoTrashNamed(item.name)}
          data-held={hold.held ? "" : undefined}
          onClick={() => env.onRestore(receipt)}
          {...hold.handlers}
        >
          {t.undoTrash}
        </button>
      </div>
      {env.conflict?.rowId === item.id && (
        <p role="alert" ref={intoView}>
          {t.conflict}
        </p>
      )}
      {env.error?.rowId === item.id && (
        <ErrorNotice
          locale={t.dateLocale}
          placement="row"
          message={t.itemRestoreFailed(item.name)}
          onRetry={env.failedWrite ?? undefined}
          retrying={env.busy}
        />
      )}
    </li>
  );
}

/** The receipts of the items deleted in this list, above the rows. Nothing when there are none. */
export function TrashReceipts({
  receipts,
  env,
}: {
  receipts: TrashedItem[];
  env: TrashReceiptEnv;
}) {
  if (receipts.length === 0) return null;
  return (
    <ul className="shopping-items shopping-trash-receipts">
      {receipts.map((receipt) => (
        <TrashReceiptRow key={receipt.item.id} receipt={receipt} env={env} />
      ))}
    </ul>
  );
}
