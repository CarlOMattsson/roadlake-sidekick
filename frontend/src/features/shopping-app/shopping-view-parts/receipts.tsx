import { useUndoHold } from "../../mcp-apps/ui/undo-hold";
import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { ShoppingLabels } from "../labels";
import { intoView } from "./helpers";

/** What a receipt row reads from the view: the state of the write and the actions it calls. */
export type ReceiptEnv = {
  labels: ShoppingLabels;
  busy: boolean;
  conflict: { rowId: string | null } | null;
  error: { rowId: string | null } | null;
  failedWrite: (() => void) | null;
  /** The time to undo is up: the receipt goes. */
  onRelease: (id: string) => void;
};

/** One receipt: what happened to the item with `id`, and the write that takes it back. */
export type Receipt = {
  id: string;
  /** The line that says what happened, with the item's name. */
  line: string;
  /** The visible word of the Undo button, and its name for assistive technology. */
  undo: string;
  undoLabel: string;
  /** What a failed Undo says. */
  failure: string;
  /** The change is not confirmed yet, so there is nothing to undo: Undo waits. */
  pending?: boolean;
  onUndo: () => void;
};

/**
 * One receipt row (designsystem §3 Ångra): the line of what happened ("Borttagen: name", "Flyttad till Helg: name")
 * and its Undo, which runs out after the family's time to undo and stands still while the pointer is over it or
 * focus is in it. A failed Undo says so in the row and offers Try again with the same key.
 */
function ReceiptRow({ receipt, env }: { receipt: Receipt; env: ReceiptEnv }) {
  const { labels: t } = env;
  const hold = useUndoHold(true, () => env.onRelease(receipt.id));
  return (
    <li className="shopping-receipt" aria-busy={env.busy || undefined}>
      <div className="shopping-toolbar">
        <p role="status" className="shopping-receipt-line">
          {receipt.line}
        </p>
        <button
          type="button"
          className="sk-btn--secondary sk-btn--compact sk-undo-time shopping-undo"
          disabled={env.busy || receipt.pending}
          aria-label={receipt.undoLabel}
          data-held={hold.held ? "" : undefined}
          onClick={receipt.onUndo}
          {...hold.handlers}
        >
          {receipt.undo}
        </button>
      </div>
      {env.conflict?.rowId === receipt.id && (
        <p role="alert" ref={intoView}>
          {t.conflict}
        </p>
      )}
      {env.error?.rowId === receipt.id && (
        <ErrorNotice
          locale={t.dateLocale}
          placement="row"
          message={receipt.failure}
          onRetry={env.failedWrite ?? undefined}
          retrying={env.busy}
        />
      )}
    </li>
  );
}

/** The receipts of the changes made in this list, above the rows. Nothing when there are none. */
export function Receipts({
  receipts,
  env,
}: {
  receipts: Receipt[];
  env: ReceiptEnv;
}) {
  if (receipts.length === 0) return null;
  return (
    <ul className="shopping-items shopping-receipts">
      {receipts.map((receipt) => (
        <ReceiptRow key={receipt.id} receipt={receipt} env={env} />
      ))}
    </ul>
  );
}
