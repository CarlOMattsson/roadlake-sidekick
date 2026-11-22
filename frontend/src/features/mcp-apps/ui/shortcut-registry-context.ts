import { createContext, useContext, useSyncExternalStore } from "react";

/**
 * The list of shortcuts the help sheet shows, and the "single-character shortcuts" switch (WCAG 2.1.4). The shell
 * provides one registry; each room registers its group with `useRoomShortcuts` (shortcut-registry.ts) and
 * `useShortcuts` (shortcuts.ts) reads the switch on every key. This file holds the registry itself and its
 * context, so shortcuts.ts can read the context without importing the hooks that import shortcuts.ts.
 */

/** One row of the help sheet. `keys` are bindings as `useShortcuts` writes them ("?", "g 1", "ArrowDown"); several are alternatives. */
export type ShortcutHelpEntry = { keys: readonly string[]; label: string };
export type ShortcutHelpGroup = {
  id: string;
  title: string;
  entries: readonly ShortcutHelpEntry[];
};

export type ShortcutRegistry = {
  /** Adds or replaces the group `id` (an existing group keeps its place); `undefined` removes it. */
  set: (id: string, group: ShortcutHelpGroup | undefined) => void;
  /** In registration order. The same reference until something changes, so `useSyncExternalStore` stays quiet. */
  groups: () => readonly ShortcutHelpGroup[];
  subscribe: (listener: () => void) => () => void;
  charKeys: () => boolean;
  setCharKeys: (on: boolean) => void;
};

export function createShortcutRegistry(): ShortcutRegistry {
  const byId = new Map<string, ShortcutHelpGroup>();
  const listeners = new Set<() => void>();
  let snapshot: readonly ShortcutHelpGroup[] = [];
  let charKeysOn = true;

  const notify = () => {
    for (const listener of [...listeners]) listener();
  };

  return {
    set(id, group) {
      if (group === undefined) {
        if (!byId.delete(id)) return;
      } else {
        byId.set(id, group);
      }
      snapshot = [...byId.values()];
      notify();
    },
    groups: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    charKeys: () => charKeysOn,
    setCharKeys(on) {
      if (on === charKeysOn) return;
      charKeysOn = on;
      notify();
    },
  };
}

export const ShortcutRegistryContext = createContext<
  ShortcutRegistry | undefined
>(undefined);

const noGroups: readonly ShortcutHelpGroup[] = [];
const noSubscribe = () => () => {};
const noGroupsSnapshot = () => noGroups;
const charKeysDefault = () => true;

/** The groups for the help sheet; empty outside a provider. */
export function useShortcutGroups(): readonly ShortcutHelpGroup[] {
  const registry = useContext(ShortcutRegistryContext);
  return useSyncExternalStore(
    registry ? registry.subscribe : noSubscribe,
    registry ? registry.groups : noGroupsSnapshot,
  );
}

/** Whether single-character shortcuts are on; true outside a provider. */
export function useCharKeys(): boolean {
  const registry = useContext(ShortcutRegistryContext);
  return useSyncExternalStore(
    registry ? registry.subscribe : noSubscribe,
    registry ? registry.charKeys : charKeysDefault,
  );
}

/**
 * How a room's ⋯ opens the keyboard help ("Kortkommandon ?", desktop spec 2.6): set by the shell in fullscreen, with the
 * row's label in the app's language. Absent (an inline card, a host the shell does not drive): no row.
 */
export type ShortcutHelpOpener = { open: () => void; label: string };

export const ShortcutHelpOpenerContext = createContext<
  ShortcutHelpOpener | undefined
>(undefined);
