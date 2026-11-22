import { useLayoutEffect, useRef } from "react";
import type { FocusEvent, KeyboardEvent } from "react";
import type { ShoppingItem } from "../transport";
import { useCharKeys } from "../../mcp-apps/ui/shortcut-registry-context";
import type { RowEnv } from "./row-parts";

/**
 * The store view's rows as one stop of the Tab order (fullscreen only): roving focus over the rows of the whole list,
 * across the store groups and the bought fold. The row's main button (its name) is the row's stop; of all rows one has
 * it (`tabIndex` 0), the last one focused, else the first, and every other control of every row is reached by
 * the ← and → keys only (`tabIndex` -1). An inline card keeps the plain Tab order of its phone.
 *
 * Keys are read on the row's line (its ring, name, − + and ⋯), not on the window: the arrows must not take the page's
 * own scrolling when the focus is elsewhere, and they work the same in every list without a registry entry per
 * group. j, k and x are single-character keys and follow the "single-character shortcuts" switch (WCAG 2.1.4).
 *
 *  - ↓ / j and ↑ / k: the next / previous row's name; Home and End: the first and the last (no wrap).
 *  - ← and →: the previous / next control of the same row (ring, name, −, +, ⋯).
 *  - x: the ring (buys the row, or makes it open again).
 *  - Delete and Backspace: Delete (to the trash, with Ångra) on a row that has the row menu's Delete.
 *
 * The tab stops are set on the DOM (not as `tabIndex` props), because one row's stop depends on all the others and
 * the rows are drawn by two lists (the open groups and the bought fold) that share no parent in React.
 */

/** The fullscreen view: only there the rows are one stop. */
const ROOT = ".shopping-fullscreen";
const LINE = ".shopping-store-line";
const NAME = ".shopping-store-row";

/** The row each fullscreen view last had its focus on (the node itself, so a row that is drawn again loses it). */
const stops = new WeakMap<Element, HTMLElement>();

/** A control the arrow keys can reach: enabled and not in the hidden copy of the quick changes a held row keeps. */
const reachable = (button: HTMLButtonElement) =>
  !button.disabled && !button.closest('[aria-hidden="true"]');

const namesIn = (root: Element) =>
  [...root.querySelectorAll<HTMLButtonElement>(NAME)].filter(reachable);

/** The row that has the stop: the last one focused while it is still drawn, else the first that can be focused. */
function stopOf(root: Element): HTMLElement | null {
  const kept = stops.get(root);
  if (kept?.isConnected && kept instanceof HTMLButtonElement && reachable(kept))
    return kept;
  return namesIn(root)[0] ?? null;
}

/** Sets the tab stops of one row's line: its name when it is the stop, nothing else. */
function setStops(line: Element, root: Element) {
  const stop = stopOf(root);
  for (const button of line.querySelectorAll<HTMLButtonElement>("button"))
    button.tabIndex = button === stop ? 0 : -1;
}

/** The row's controls in order, ring first. */
const controlsOf = (line: Element) =>
  [...line.querySelectorAll<HTMLButtonElement>("button")].filter(reachable);

/** The key names that move over rows or controls; the ones of one character follow the single-character switch. */
function rowKey(key: string): "next" | "previous" | "first" | "last" | null {
  switch (key) {
    case "ArrowDown":
    case "j":
      return "next";
    case "ArrowUp":
    case "k":
      return "previous";
    case "Home":
      return "first";
    case "End":
      return "last";
    default:
      return null;
  }
}

export function useRowKeys(
  item: ShoppingItem,
  env: RowEnv,
  /** The row has the quick changes: it is open, can be changed and stands in its place. */
  quick: boolean,
) {
  const line = useRef<HTMLDivElement>(null);
  const charKeys = useCharKeys();

  // After every draw of this row: its own buttons take their stops (the view's other rows do the same for theirs).
  useLayoutEffect(() => {
    const node = line.current;
    const root = node?.closest(ROOT);
    if (node && root) setStops(node, root);
  });

  function onFocus(event: FocusEvent<HTMLElement>) {
    const node = event.currentTarget;
    const root = node.closest(ROOT);
    if (!root || !(event.target instanceof HTMLButtonElement)) return;
    const name = node.querySelector<HTMLElement>(NAME);
    if (!name || stops.get(root) === name) return;
    const before = stopOf(root)?.closest(LINE);
    stops.set(root, name);
    if (before) setStops(before, root);
    setStops(node, root);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.defaultPrevented || event.nativeEvent.isComposing) return;
    if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey)
      return;
    const node = event.currentTarget;
    const root = node.closest(ROOT);
    const target = event.target;
    if (!root || !(target instanceof HTMLButtonElement)) return;
    // The single-character keys can be switched off (WCAG 2.1.4); the others stay.
    if (event.key.length === 1 && !charKeys) return;

    const move = rowKey(event.key);
    if (move) {
      const names = namesIn(root);
      const at = names.findIndex((name) => name.closest(LINE) === node);
      const next =
        move === "first"
          ? 0
          : move === "last"
            ? names.length - 1
            : at + (move === "next" ? 1 : -1);
      event.preventDefault();
      names[Math.min(Math.max(next, 0), names.length - 1)]?.focus();
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      const controls = controlsOf(node);
      const at = controls.indexOf(target);
      if (at < 0) return;
      event.preventDefault();
      const next = at + (event.key === "ArrowRight" ? 1 : -1);
      controls[Math.min(Math.max(next, 0), controls.length - 1)]?.focus();
      return;
    }
    if (event.key === "x") {
      const ring = node.querySelector<HTMLButtonElement>(".shopping-ring");
      if (!ring || ring.disabled) return;
      event.preventDefault();
      ring.click();
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      if (!quick || !env.onTrash || env.busy) return;
      event.preventDefault();
      // The row is gone once it is in the trash: the focus goes to its neighbour.
      env.onTrash(item, () => env.onCloseEditor(item.id));
    }
  }

  return { line, onKeyDown, onFocus };
}
