import { useContext, useEffect, useMemo } from "react";

import { RoomSurfaceContext } from "./room-context";
import {
  ShortcutRegistryContext,
  type ShortcutHelpEntry,
  type ShortcutHelpGroup,
} from "./shortcut-registry-context";
import {
  useShortcuts,
  type ShortcutMap,
  type ShortcutOptions,
} from "./shortcuts";

export * from "./shortcut-registry-context";

type HelpLabels = {
  id: string;
  title: string;
  /** Binding to label. A binding without a label works but is not listed; bindings with one label share a row. */
  labels: Readonly<Record<string, string>>;
};

/** The rows for the bindings of `map` that have a label, in the map's order, bindings with the same label merged. */
function entriesFor(
  map: ShortcutMap,
  labels: Readonly<Record<string, string>>,
): ShortcutHelpEntry[] {
  const rows = new Map<string, string[]>();
  for (const binding of Object.keys(map)) {
    const label = labels[binding];
    if (label === undefined) continue;
    const keys = rows.get(label);
    if (keys) keys.push(binding);
    else rows.set(label, [binding]);
  }
  return [...rows].map(([label, keys]) => ({ keys, label }));
}

/**
 * `useShortcuts` plus the group's rows in the help sheet. The group is listed while this layer is active and
 * `options.enabled` is not false, and removed when it turns inactive or unmounts.
 */
export function useRoomShortcuts(
  map: ShortcutMap,
  help: HelpLabels,
  options: ShortcutOptions = {},
): void {
  useShortcuts(map, options);
  const registry = useContext(ShortcutRegistryContext);
  const { active } = useContext(RoomSurfaceContext);
  const listed = options.enabled !== false && active;
  const { id, title } = help;
  // A stable key of what the sheet shows, so a new map or labels object each render does not re-register.
  const key = JSON.stringify(entriesFor(map, help.labels));
  const group = useMemo<ShortcutHelpGroup | undefined>(() => {
    const entries = JSON.parse(key) as ShortcutHelpEntry[];
    return entries.length > 0 ? { id, title, entries } : undefined;
  }, [key, id, title]);

  // Set in place (a changed group keeps its position); removed only when the group stops being listed.
  useEffect(() => {
    if (registry && listed) registry.set(id, group);
  }, [registry, listed, id, group]);
  useEffect(() => {
    if (!registry || !listed) return;
    return () => registry.set(id, undefined);
  }, [registry, listed, id]);
}

const keyNames: Readonly<Record<string, string>> = {
  ArrowDown: "↓",
  ArrowUp: "↑",
  ArrowLeft: "←",
  ArrowRight: "→",
  Escape: "Esc",
};

function isMac(): boolean {
  return (
    typeof navigator !== "undefined" &&
    /Mac|iPhone|iPad/.test(navigator.platform)
  );
}

/**
 * How a binding reads on a keycap row: one string per `<kbd>`. "g 1" is two keys, "Mod+Enter" is Ctrl (⌘ on a Mac)
 * and Enter, "ArrowDown" is ↓.
 */
export function shortcutKeyParts(binding: string, mac = isMac()): string[] {
  return binding
    .trim()
    .split(/\s+/)
    .flatMap((step) =>
      step.split("+").map((part) => {
        if (part === "Mod") return mac ? "⌘" : "Ctrl";
        return keyNames[part] ?? part;
      }),
    );
}
