import type { RefObject } from "react";
import type {
  ShoppingInput,
  ShoppingItem,
  ShoppingTransport,
} from "../transport";
import type { ShoppingLabels } from "../labels";
import type { RowQueue } from "../../mcp-apps/ui/row-queue";
import { FailureNotice } from "./failure-notice";
import { intoView } from "./helpers";

/** Everything an item row reads from the view: the state it draws and the actions it calls. */
export type RowEnv = {
  labels: ShoppingLabels;
  /** The row's hint: the long press on touch, the right click and Shift+F10 with a fine pointer. */
  holdTip: string;
  /** The list is archived: its rows cannot be changed. */
  archived: boolean | undefined;
  busy: boolean;
  /** The folded compact view: a row is the name only. */
  folded: boolean;
  held: Record<string, ShoppingItem>;
  rowQueue: RowQueue;
  /** Purchases waiting in the phone's outbox for a network (item id → the state that will be sent). */
  waiting: Record<string, boolean>;
  conflict: { rowId: string | null } | null;
  error: { rowId: string | null } | null;
  failedWrite: (() => void) | null;
  editing: ShoppingItem | null;
  editorByKey: RefObject<boolean>;
  /** Registers the row's main button (null when it unmounts), so closing the change form can refocus it. */
  registerRow: (id: string, node: HTMLButtonElement | null) => void;
  contacts: ShoppingTransport["contacts"];
  onToggle: (item: ShoppingItem) => void;
  onRefresh: () => void;
  /** Opens the change form (store view). */
  onOpenEditor: (item: ShoppingItem, byKey?: boolean) => void;
  /** Closes the change form and gives the focus back to the row's button (store view). */
  onCloseEditor: (id: string) => void;
  /** Sets the open change form without a focus return (list view). */
  onEdit: (item: ShoppingItem | null) => void;
  /** Writes the changed item; `done` runs once it is saved. */
  onSave: (item: ShoppingItem, input: ShoppingInput, done: () => void) => void;
};

/**
 * A held row's Undo (designsystem §3 Ångra): a compact secondary button in the row's trailing slot, beside the
 * label and never inside it (a button is labelable), on the title line's middle. The row keeps its height.
 */
export function undoButton(item: ShoppingItem, env: RowEnv) {
  const { labels: t } = env;
  return (
    <button
      type="button"
      className="sk-btn--secondary sk-btn--compact shopping-undo"
      disabled={env.archived || item.id in env.waiting}
      aria-label={`${t.undoPurchase}: ${item.name}`}
      onClick={() => env.onToggle(item)}
    >
      {t.undoPurchase}
    </button>
  );
}

/**
 * A tap that waits behind the row's running write says so in the row: "Väntar…" in the meta type, muted. A purchase
 * waiting in the phone's outbox says "Väntar på anslutning" the same way.
 * The visual mark sits in the row, which is aria-busy; the announcement is one stable status region outside it.
 */
export function queuedMark(item: ShoppingItem, env: RowEnv) {
  const text =
    item.id in env.waiting
      ? env.labels.waitingForNetwork
      : env.rowQueue.queued(item.id)
        ? env.labels.queued
        : null;
  return text ? (
    <span className="sk-queued" aria-hidden="true">
      {text}
    </span>
  ) : null;
}

/** The failure of this row's own write, or its conflict, shown inside the row where the user acted. */
export function rowFailure(item: ShoppingItem, env: RowEnv) {
  if (env.conflict?.rowId === item.id)
    return (
      <p role="alert" ref={intoView}>
        {env.labels.conflict}
      </p>
    );
  if (env.error?.rowId !== item.id) return null;
  return (
    <FailureNotice
      labels={env.labels}
      retry={env.failedWrite ?? undefined}
      busy={env.busy}
      placement="row"
      brief={env.editing?.id !== item.id}
      onRefresh={env.onRefresh}
    />
  );
}
