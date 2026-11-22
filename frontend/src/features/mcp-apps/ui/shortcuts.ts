import { useContext, useEffect, useLayoutEffect, useRef } from "react";

import { RoomSurfaceContext } from "./room-context";
import { ShortcutRegistryContext } from "./shortcut-registry-context";

/**
 * Keyboard shortcuts for fullscreen MCP App views (design language section 3.8). Inline views
 * have no shortcuts; callers pass `enabled: false` there.
 *
 * A map binds a key string to an action. A key string is either one combo (`"j"`, `"?"`,
 * `"ArrowDown"`, `"Shift+ArrowRight"`, `"Ctrl+Enter"`, `"Mod+Enter"`) or a sequence of combos
 * separated by spaces (`"g a"`). `Mod` matches Ctrl or Cmd. Modifiers must match exactly: a plain
 * key ignores Ctrl, Alt and Meta combinations, so those only fire when listed. A printable
 * character (`"?"`, `"j"`) ignores Shift because the produced character already carries it; write
 * shifted letters as the character itself (`"J"`). A sequence must complete within one second of
 * its previous key. A single-key binding wins over a sequence that starts with the same key.
 *
 * Keys typed into a field (input, textarea, select, contenteditable), keys inside an open menu
 * (`[data-menu]`) or a dialog, and IME composition are ignored. Single-character bindings (every
 * step a printable character without Ctrl, Alt or Meta, such as `j`, `?` or `g 1`) can be switched
 * off through the shortcut registry's `charKeys` (WCAG 2.1.4); `ArrowDown`, `Enter`, `Escape` and
 * combos with a modifier stay. A handled key calls `preventDefault`, so Space does not scroll and Backspace does not
 * navigate back. Actions are read from the latest map on each key, so callers do not need to
 * memoise the map.
 */

export type ShortcutAction = () => void;
export type ShortcutMap = Readonly<Record<string, ShortcutAction>>;
export type ShortcutOptions = {
  /** When false no listener is attached and any partial sequence is dropped. Defaults to true. */
  enabled?: boolean;
  /**
   * Listen in the capture phase. The shell's global map (`?`, `g 1`) uses it so `g` then `1` does not first
   * reach a room's own `1`: two listeners, and the one that calls `preventDefault` first wins. Defaults to false.
   */
  capture?: boolean;
};

export const SEQUENCE_TIMEOUT_MS = 1000;

type Combo = {
  key: string;
  ctrl: boolean;
  alt: boolean;
  meta: boolean;
  shift: boolean;
  mod: boolean;
};

type Binding = {
  steps: Combo[];
  action: ShortcutAction;
  /** Every step is a printable character without Ctrl, Alt, Meta or Mod: the kind a user can switch off. */
  chars: boolean;
};

type Progress = {
  binding: Binding;
  next: number;
};

type Pending = {
  at: number;
  matches: Progress[];
};

function parseCombo(text: string): Combo {
  const parts = text.split("+");
  const key = parts.pop() ?? "";
  const combo: Combo = {
    key,
    ctrl: false,
    alt: false,
    meta: false,
    shift: false,
    mod: false,
  };
  for (const part of parts) {
    switch (part) {
      case "Ctrl":
        combo.ctrl = true;
        break;
      case "Alt":
        combo.alt = true;
        break;
      case "Meta":
        combo.meta = true;
        break;
      case "Shift":
        combo.shift = true;
        break;
      case "Mod":
        combo.mod = true;
        break;
      default:
        throw new Error(`Unknown shortcut modifier "${part}" in "${text}"`);
    }
  }
  return combo;
}

function compileShortcuts(map: ShortcutMap): Binding[] {
  return Object.entries(map).map(([text, action]) => {
    const steps = text.trim().split(/\s+/).map(parseCombo);
    const chars = steps.every(
      (step) =>
        step.key.length === 1 &&
        !step.ctrl &&
        !step.alt &&
        !step.meta &&
        !step.mod,
    );
    return { steps, action, chars };
  });
}

function matchesCombo(combo: Combo, event: KeyboardEvent): boolean {
  if (combo.key !== event.key) return false;
  if (combo.alt !== event.altKey) return false;
  if (combo.mod) {
    if (!event.ctrlKey && !event.metaKey) return false;
  } else if (combo.ctrl !== event.ctrlKey || combo.meta !== event.metaKey) {
    return false;
  }
  const printable = combo.key.length === 1;
  return printable || combo.shift === event.shiftKey;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target.closest('[contenteditable]:not([contenteditable="false"])'))
    return true;
  return target.matches("input, textarea, select");
}

/** A key inside an open menu or a dialog belongs to that layer, which handles its own keys. */
function isInsideLayer(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest("[data-menu], dialog, [role='dialog']") !== null
  );
}

/**
 * Binds the keyboard shortcuts in `map` to the window while `enabled` is true.
 */
export function useShortcuts(
  map: ShortcutMap,
  options: ShortcutOptions = {},
): void {
  // A room that is mounted but hidden (another room, or a cross-link above it) has no shortcuts.
  const { active } = useContext(RoomSurfaceContext);
  const enabled = (options.enabled ?? true) && active;
  const capture = options.capture ?? false;
  const mapRef = useRef(map);
  const registry = useContext(ShortcutRegistryContext);
  const registryRef = useRef(registry);

  // Layout effect, not a passive one: the map must be current as soon as the DOM shows the new
  // render. A passive effect can run a macrotask later, so a key pressed right after the view
  // changed would act on the previous day and its previous loading state.
  useLayoutEffect(() => {
    mapRef.current = map;
    registryRef.current = registry;
  });

  useEffect(() => {
    if (!enabled) return;

    let pending: Pending | null = null;

    const run = (binding: Binding, event: KeyboardEvent) => {
      event.preventDefault();
      binding.action();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.isComposing ||
        event.key === "Process"
      )
        return;
      if (isEditableTarget(event.target) || isInsideLayer(event.target)) {
        pending = null;
        return;
      }
      // Read at each key: the switch can change while the room stays mounted.
      const charKeys = registryRef.current?.charKeys() ?? true;

      const now = Date.now();
      const carried =
        pending !== null && now - pending.at <= SEQUENCE_TIMEOUT_MS
          ? pending.matches
          : [];
      pending = null;

      const advanced: Progress[] = [];
      for (const progress of carried) {
        const step = progress.binding.steps[progress.next];
        if (!step || !matchesCombo(step, event)) continue;
        if (!charKeys && progress.binding.chars) continue;
        if (progress.next + 1 === progress.binding.steps.length) {
          run(progress.binding, event);
          return;
        }
        advanced.push({ binding: progress.binding, next: progress.next + 1 });
      }
      if (advanced.length > 0) {
        pending = { at: now, matches: advanced };
        return;
      }

      const bindings = compileShortcuts(mapRef.current).filter(
        (binding) => charKeys || !binding.chars,
      );
      for (const binding of bindings) {
        const [first] = binding.steps;
        if (binding.steps.length === 1 && first && matchesCombo(first, event)) {
          run(binding, event);
          return;
        }
      }

      const starts: Progress[] = [];
      for (const binding of bindings) {
        const [first] = binding.steps;
        if (binding.steps.length > 1 && first && matchesCombo(first, event)) {
          starts.push({ binding, next: 1 });
        }
      }
      if (starts.length > 0) {
        pending = { at: now, matches: starts };
      }
    };

    window.addEventListener("keydown", onKeyDown, capture);
    return () => {
      window.removeEventListener("keydown", onKeyDown, capture);
    };
  }, [enabled, capture]);
}

/**
 * A fine pointer (mouse, trackpad) as the primary input: a long press does nothing there, so a row's tip names the right
 * click and Shift+F10 instead. What the host reports (`data-host-pointer`, host-style.ts: its device flags or its
 * platform) comes first, since a desktop host may run in a frame whose media query says coarse; without it the
 * frame's `(pointer: fine)` decides. False where neither can tell (no matchMedia).
 */
export const finePointer = () => {
  const host = document.documentElement.dataset.hostPointer;
  if (host === "fine" || host === "coarse") return host === "fine";
  return window.matchMedia?.("(pointer: fine)").matches === true;
};
