import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { ShoppingItem, ShoppingTransport } from "../transport";
import type { ShoppingLabels } from "../labels";
import { isEnter, MAX_ADD_ITEMS, splitItemNames } from "./helpers";
import { parseTypedItems } from "./parse-items";
import { quantityText } from "../shopping-card";
import type { Panels } from "./use-panels";
import type { ShoppingRead } from "./use-shopping-read";
import type { ShoppingWrites } from "./use-shopping-writes";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";

type Params = {
  transport: ShoppingTransport;
  labels: ShoppingLabels;
  read: ShoppingRead;
  writes: ShoppingWrites;
  store?: string;
  addOpen: boolean;
  setPanel: (key: keyof Panels, value: boolean) => void;
  /** The view's receipt bar: an add is confirmed there. */
  receipt: ReceiptState;
  /** Deletes a just-added item: the Ångra of an add of one new item. Absent when the host offers no delete. */
  discard?: (item: ShoppingItem) => Promise<boolean>;
};

/**
 * The typed-text forms and their writes: new list, rename, the batch of item names and the one-item create
 * field of the store view. Each runs from a button click or Enter, never from a submit event (the App iframe is
 * sandboxed without allow-forms, where the browser never dispatches submit).
 */
export function useWriteForms({
  transport,
  labels: t,
  read,
  writes,
  store,
  addOpen,
  setPanel,
  receipt,
  discard,
}: Params) {
  const { id, setId, setOffset, detail, busy } = read;
  const { write } = writes;
  const list = detail?.shopping_list;
  // The name typed in the fullscreen "Edit list" field. It starts from the list's name each time the edit opens.
  const [renameName, setRenameName] = useState("");
  const [names, setNames] = useState("");
  function changeNames(value: string) {
    setNames(value);
  }
  const [invalidBatch, setInvalidBatch] = useState(false);
  // The rows the last add made or grew: the folded card shows them also past its row budget, so what was typed is seen.
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
  const addButton = useRef<HTMLButtonElement>(null);
  // Closing the field gives the focus back to "+ Add item" once that row is drawn again.
  const refocusAdd = useRef(false);
  useEffect(() => {
    if (addOpen || !refocusAdd.current) return;
    refocusAdd.current = false;
    addButton.current?.focus();
  }, [addOpen]);
  /** The "Add item" row opens the field. */
  function openAddField() {
    setPanel("addOpen", true);
  }
  /** The + of the fullscreen header opens or closes the field. */
  function toggleAddField() {
    setPanel("addOpen", !addOpen);
  }
  function closeAddField() {
    refocusAdd.current = true;
    setPanel("addOpen", false);
  }
  /** Creates a list with this name and opens it; false when nothing was written. */
  function createNamed(name: string): Promise<boolean> {
    const value = name.trim();
    if (!value) return Promise.resolve(false);
    return write(`create:${value}`, async (key) => {
      const result = await transport.create(value, key);
      setId(result.shopping_list.id);
      setOffset(0);
    });
  }
  // The name goes to update_shopping_list with the version that was read; the edit closes once it is saved.
  function rename() {
    const name = renameName.trim();
    if (!list || !name) return;
    void write(
      JSON.stringify(["rename", list.id, list.version, name]),
      (key) => transport.rename(list, name, list.archived, key),
      () => setPanel("editOpen", false),
    );
  }
  /**
   * Adds the typed items through one write, for the batch field and the create field alike. Commas separate several
   * items, and an amount in the text ("2 l mjölk") is read as the item's quantity and unit. In a shop view the items
   * go to that shop, so they show at once; an open item with the same name and unit takes the amount instead of a new
   * row. The receipt bar says what was added and what joined an item that was already there (`newItemPrefix` with the
   * items and their shop), since in a long list the new row may stand out of sight; the field keeps the focus and the
   * list does not scroll. One new item has Ångra, which deletes it again. `saved` runs on success; a failure keeps the
   * typed text and shows its line.
   */
  function addTyped(text: string, rowId: string | null, saved?: () => void) {
    const typed = parseTypedItems(text);
    if (!typed.length || typed.length > MAX_ADD_ITEMS)
      return Promise.resolve(false);
    return write(
      JSON.stringify(["add", id, typed]),
      (key) => transport.add(id, typed, key, { store, mergeDuplicates: true }),
      (result) => {
        const entries =
          (
            result as {
              items?: { item: ShoppingItem; merged?: boolean }[];
            } | null
          )?.items ?? [];
        const added = entries.map((entry) =>
          entry.merged
            ? {
                ...entry.item,
                name: t.mergedNow(
                  entry.item.name,
                  quantityText(entry.item, t.dateLocale),
                ),
              }
            : entry.item,
        );
        setFresh(new Set(added.map((item) => item.id)));
        const names = added.length
          ? added.map((item) => item.name)
          : typed.map((item) => item.name);
        // The shop is named when every item went to the same one.
        const shops = new Set(added.map((item) => item.store?.trim() ?? ""));
        const [shop] = shops.size === 1 ? shops : [];
        // Ångra of an add takes back one new row; an amount that joined an item already there is not a row to delete.
        const [only] = entries;
        const undoable =
          entries.length === 1 && only && !only.merged && discard
            ? only.item
            : undefined;
        receipt.show({
          message: `${t.newItemPrefix} ${names.join(", ")}${shop ? ` · ${shop}` : ""}`,
          undo:
            undoable && discard
              ? { label: t.undoAdd, onUndo: () => discard(undoable) }
              : undefined,
        });
        // Without a network the phone queues the add and answers with stand-in rows that wait in its outbox: the
        // receipt then says the items are sent once the network is back, not that they were added.
        const offline = transport.offline;
        if (offline && added.length)
          void offline.queuedPurchases().then(
            (queued) => {
              if (added.some((item) => queued.has(item.id)))
                receipt.show({ message: t.addQueued(names.join(", ")) });
            },
            () => undefined,
          );
        saved?.();
      },
      rowId,
    );
  }
  // The batch field of the list view.
  function add() {
    const count = splitItemNames(names).length;
    if (!count || count > MAX_ADD_ITEMS) {
      setInvalidBatch(true);
      return;
    }
    setInvalidBatch(false);
    void addTyped(names, null, () => setNames(""));
  }
  // Enter adds the batch in both the folded input and the full textarea; Shift+Enter keeps a line break.
  function batchKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (!isEnter(event) || event.shiftKey) return;
    event.preventDefault();
    if (!busy && names.trim()) add();
  }
  // The create field of "+ Add item": the field empties only when the write succeeded.
  function addOne(text: string) {
    return addTyped(text, "add");
  }
  return {
    renameName,
    setRenameName,
    names,
    changeNames,
    invalidBatch,
    fresh,
    addButton,
    openAddField,
    toggleAddField,
    closeAddField,
    createNamed,
    rename,
    add,
    batchKeyDown,
    addOne,
  };
}
