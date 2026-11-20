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
import type { MoveTarget } from "./use-quick-changes";

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
  /** The rows held in their place while the receipt bar shows, by item id: `purchased` is the state the change gave the row. */
  held: Record<string, ShoppingItem>;
  rowQueue: RowQueue;
  /** Purchases waiting in the phone's outbox for a network (item id → the state that will be sent). */
  waiting: Record<string, boolean>;
  conflict: { rowId: string | null } | null;
  error: { rowId: string | null; change?: boolean } | null;
  failedWrite: (() => void) | null;
  editing: ShoppingItem | null;
  editorByKey: RefObject<boolean>;
  /** Registers the row's main button (null when it unmounts), so closing the change form can refocus it. */
  registerRow: (id: string, node: HTMLButtonElement | null) => void;
  contacts: ShoppingTransport["contacts"];
  /** The active lists, the list an item is in included: where the change form can move it. */
  lists: { id: string; name: string }[];
  /** The shops the list's items name, one spelling each. */
  stores: string[];
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
  /** Moves the item to the trash; `done` runs once it is there. Absent when the host offers no delete. */
  onTrash?: (
    item: ShoppingItem,
    done: () => void,
  ) => void; /** Changes an open item's amount by one step (store view). Absent where a row has no quick changes. */
  onStep?: (item: ShoppingItem, delta: 1 | -1) => void;
  /** Moves an open item to another list (store view). Absent where a row has no quick changes. */
  onMove?: (item: ShoppingItem, to: MoveTarget) => void;
};

/**
 * Whether the row stands in its place with the line of what happened: the change is held (the receipt bar, which
 * carries its Ångra, still shows) and the row shows the state it gave it. A row in the `boughtCount` fold (`inPlace`
 * false) is never held.
 */
export function isHolding(item: ShoppingItem, env: RowEnv, inPlace: boolean) {
  return inPlace && env.held[item.id]?.purchased === item.purchased;
}

/** The word of what happened to a held row: `bought` or `notBought`. */
export function heldWord(item: ShoppingItem, env: RowEnv) {
  return item.purchased ? env.labels.bought : env.labels.notBought;
}

/**
 * A tap that waits behind the row's running write says so in the row: `queued` in the meta type, muted. A purchase
 * waiting in the phone's outbox says `waitingForNetwork` the same way.
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
      brief={
        env.editing?.id !== item.id && !env.error.change ? item : undefined
      }
      onRefresh={env.onRefresh}
    />
  );
}
