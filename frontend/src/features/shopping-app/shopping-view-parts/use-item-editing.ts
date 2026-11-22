import { useEffect, useRef, useState } from "react";
import type { ShoppingItem } from "../transport";
import { holdUsed } from "./helpers";

/** Where the focus goes back to once the row it was in is drawn again, or has left. */
type Refocus = {
  /** The row whose name button is the first choice. */
  id: string;
  /** Its neighbours (next, then previous) when it has left the list: a deleted or a moved item. */
  near: string[];
  /** The fullscreen view the rows are in, for the add button when no row is left. */
  root: Element | null;
};

const ROOT = ".shopping-fullscreen";

const usable = (node: HTMLButtonElement | null | undefined) =>
  node?.isConnected === true && !node.disabled;

/**
 * The row whose change form is open. The store view's change form (tap, long press, Shift+F10): closing it gives
 * the focus back to the row's button.
 *
 * `closeEditor(id)` also names where the focus goes when a row is changed or leaves without the form (the row menu's
 * Delete and move): the row's own button, which is also drawn again when a save moved the item to another store group,
 * else the next row's, else the previous row's, else the view's add button. The focus is only set while it has been
 * dropped on the page (an unmounted form or row), never taken from a control the user has moved to, and the choice
 * lapses at the user's next key or press.
 */
export function useItemEditing(archived: boolean | undefined) {
  const [editing, setEditing] = useState<ShoppingItem | null>(null);
  const rowButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const refocus = useRef<Refocus | null>(null);
  const editorByKey = useRef(false);
  // After every draw: the focus follows a row that was drawn again or has left.
  useEffect(() => {
    const want = refocus.current;
    if (!want) return;
    const active = document.activeElement;
    if (active && active !== document.body) return;
    const node = [want.id, ...want.near]
      .map((id) => rowButtons.current[id])
      .find(usable);
    const target =
      node ?? want.root?.querySelector<HTMLElement>(".shopping-add") ?? null;
    if (!target) return;
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ block: "nearest" });
  });
  // The next key or press is the user's: what was asked for has done its part.
  useEffect(() => {
    const lapse = () => {
      refocus.current = null;
    };
    document.addEventListener("keydown", lapse, true);
    document.addEventListener("pointerdown", lapse, true);
    return () => {
      document.removeEventListener("keydown", lapse, true);
      document.removeEventListener("pointerdown", lapse, true);
    };
  }, []);
  /** The ref callback of a row's main button, so the focus can go back to it. */
  function registerRow(id: string, node: HTMLButtonElement | null) {
    rowButtons.current[id] = node;
  }
  /** The ids of the rows next to `id` in the order they are drawn: the next one, then the previous one. */
  function neighbours(id: string): string[] {
    const own = rowButtons.current[id];
    if (!own?.isConnected) return [];
    const rows = Object.entries(rowButtons.current)
      .filter((entry): entry is [string, HTMLButtonElement] => usable(entry[1]))
      .sort(([, a], [, b]) =>
        a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING
          ? -1
          : 1,
      );
    const at = rows.findIndex(([key]) => key === id);
    return [rows[at + 1]?.[0], rows[at - 1]?.[0]].filter(
      (key): key is string => key !== undefined,
    );
  }
  function closeEditor(id: string) {
    refocus.current = {
      id,
      near: neighbours(id),
      root: rowButtons.current[id]?.closest(ROOT) ?? null,
    };
    setEditing(null);
  }
  // `byKey`: Shift+F10 or the menu key. The form then takes the focus on its first field, so Escape closes it at once
  // and the focus goes back to the row. A long press leaves the focus, so no keyboard rises.
  function openEditor(item: ShoppingItem, byKey = false) {
    if (archived) return;
    holdUsed();
    refocus.current = null;
    editorByKey.current = byKey;
    setEditing(item);
  }
  return {
    editing,
    setEditing,
    registerRow,
    editorByKey,
    closeEditor,
    openEditor,
  };
}
