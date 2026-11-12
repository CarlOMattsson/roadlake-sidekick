import { useEffect, useRef, useState } from "react";
import type { ShoppingItem } from "../transport";
import { holdUsed } from "./helpers";

/**
 * The row whose change form is open. The store view's change form (tap, long press, Shift+F10): closing it gives
 * the focus back to the row's button.
 */
export function useItemEditing(archived: boolean | undefined) {
  const [editing, setEditing] = useState<ShoppingItem | null>(null);
  const rowButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const refocusRow = useRef<string | null>(null);
  const editorByKey = useRef(false);
  useEffect(() => {
    if (editing || !refocusRow.current) return;
    const id = refocusRow.current;
    refocusRow.current = null;
    rowButtons.current[id]?.focus();
  }, [editing]);
  /** The ref callback of a row's main button, so the focus can go back to it. */
  function registerRow(id: string, node: HTMLButtonElement | null) {
    rowButtons.current[id] = node;
  }
  function closeEditor(id: string) {
    refocusRow.current = id;
    setEditing(null);
  }
  // `byKey`: Shift+F10 or the menu key. The form then takes the focus on its first field, so Escape closes it at once
  // and the focus goes back to the row. A long press leaves the focus, so no keyboard rises.
  function openEditor(item: ShoppingItem, byKey = false) {
    if (archived) return;
    holdUsed();
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
